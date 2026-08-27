"""Policy-aware model routing with reproducible, explainable selection.

Safety and data policy are hard filters; cost and latency are optimization
signals. Every decision records the matching rules and a concise public reason —
never private chain-of-thought. Fallback re-runs model inference only: it never
crosses a locality boundary, never lowers data trust, and never repeats a tool
action (a caller concern the router does not trigger).
"""

from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel, ConfigDict, Field

from .registry import ModelRegistry, ModelSpec

# fast < standard < slow
_LATENCY_ORDER = {"fast": 0, "standard": 1, "slow": 2}


def _latency_rank(value: str) -> int:
    return _LATENCY_ORDER.get(value, 1)


class RoutingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_class: str = "analysis"
    required_capabilities: List[str] = Field(default_factory=list)
    data_classification: str = "internal"
    local_only: bool = False
    allowlist: List[str] = Field(default_factory=list)
    max_context: int = 0
    quality_threshold: float = 0.0
    latency_deadline_class: str = ""
    cost_budget_per_mtok: float = 0.0
    pinned_model: str = ""
    allow_fallback: bool = True


class RoutingRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    when_task_class: str = ""
    when_data_classification: str = ""
    require_locality: str = ""
    require_capabilities: List[str] = Field(default_factory=list)

    def matches(self, request: RoutingRequest) -> bool:
        if self.when_task_class and self.when_task_class != request.task_class:
            return False
        if self.when_data_classification and self.when_data_classification != request.data_classification:
            return False
        return True


class RoutingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = ""
    selected: bool = False
    reason: str = ""
    matched_rules: List[str] = Field(default_factory=list)
    fallback_candidates: List[str] = Field(default_factory=list)
    tried: List[str] = Field(default_factory=list)


DEFAULT_RULES: List[RoutingRule] = [
    RoutingRule(
        name="confidential-local",
        when_data_classification="confidential",
        require_locality="local",
    ),
    RoutingRule(
        name="restricted-local",
        when_data_classification="restricted",
        require_locality="local",
    ),
    RoutingRule(
        name="structured-planning",
        when_task_class="planning",
        require_capabilities=["structured_output"],
    ),
]


class ModelRouter:
    def __init__(
        self,
        registry: ModelRegistry,
        rules: List[RoutingRule] | None = None,
    ) -> None:
        self._registry = registry
        self._rules = rules if rules is not None else list(DEFAULT_RULES)

    def _effective(self, request: RoutingRequest) -> tuple[RoutingRequest, List[str]]:
        matched: List[str] = []
        local_only = request.local_only
        required = list(request.required_capabilities)
        for rule in self._rules:
            if not rule.matches(request):
                continue
            matched.append(rule.name)
            if rule.require_locality == "local":
                local_only = True
            for capability in rule.require_capabilities:
                if capability not in required:
                    required.append(capability)
        effective = request.model_copy(update={"local_only": local_only, "required_capabilities": required})
        return effective, matched

    def _passes_hard_filters(self, spec: ModelSpec, request: RoutingRequest) -> bool:
        if not spec.available or spec.rate_limited:
            return False
        if request.allowlist and spec.id not in request.allowlist and spec.provider not in request.allowlist:
            return False
        if not spec.data_policy.accepts(request.data_classification):
            return False
        if request.local_only and spec.data_policy.locality != "local":
            return False
        if not spec.has_capabilities(request.required_capabilities):
            return False
        if request.max_context and spec.context_limit < request.max_context:
            return False
        if request.quality_threshold and spec.quality_for(request.task_class) < request.quality_threshold:
            return False
        if request.latency_deadline_class and _latency_rank(spec.latency_class) > _latency_rank(request.latency_deadline_class):
            return False
        if request.cost_budget_per_mtok and spec.cost.input_per_mtok > request.cost_budget_per_mtok:
            return False
        return True

    def _rank_key(self, spec: ModelSpec, task_class: str):
        # quality desc, latency asc, cost asc, id asc — deterministic/reproducible
        return (
            -spec.quality_for(task_class),
            _latency_rank(spec.latency_class),
            spec.cost.input_per_mtok,
            spec.id,
        )

    def route(self, request: RoutingRequest) -> RoutingDecision:
        if request.pinned_model:
            spec = self._registry.get(request.pinned_model)
            if spec is None:
                return RoutingDecision(reason=f"pinned model '{request.pinned_model}' is not registered")
            if not self._passes_hard_filters(spec, request):
                return RoutingDecision(reason=f"pinned model '{request.pinned_model}' fails a hard policy filter")
            return RoutingDecision(
                model_id=spec.id, selected=True, reason="pinned model", tried=[spec.id],
                fallback_candidates=self._fallback_pool(spec, request, [spec.id]),
            )

        effective, matched = self._effective(request)
        eligible = [s for s in self._registry.all() if self._passes_hard_filters(s, effective)]
        if not eligible:
            detail = "local-only requirement with no registered local model" if effective.local_only else "no model satisfies the policy and capability filters"
            return RoutingDecision(reason=detail, matched_rules=matched)

        eligible.sort(key=lambda s: self._rank_key(s, effective.task_class))
        chosen = eligible[0]
        reason = (
            f"task={effective.task_class}; passed policy/capability/health filters; "
            f"ranked top by quality then latency then cost"
        )
        return RoutingDecision(
            model_id=chosen.id,
            selected=True,
            reason=reason,
            matched_rules=matched,
            tried=[chosen.id],
            fallback_candidates=self._fallback_pool(chosen, effective, [chosen.id]),
        )

    def _fallback_pool(self, current: ModelSpec, request: RoutingRequest, tried: List[str]) -> List[str]:
        pool = []
        for spec in self._registry.in_group(current.fallback_group):
            if spec.id in tried:
                continue
            if spec.data_policy.locality != current.data_policy.locality:
                continue  # never cross a locality boundary
            if not self._passes_hard_filters(spec, request):
                continue
            pool.append(spec.id)
        pool.sort(key=lambda sid: self._rank_key(self._registry.get(sid), request.task_class))
        return pool

    def fallback(self, decision: RoutingDecision, request: RoutingRequest) -> RoutingDecision:
        """Select the next safe alternative after a model-inference failure."""
        if not request.allow_fallback:
            return RoutingDecision(reason="fallback disabled for this request", tried=decision.tried)
        current = self._registry.get(decision.model_id)
        if current is None:
            return RoutingDecision(reason="no current model to fall back from", tried=decision.tried)
        pool = self._fallback_pool(current, request, decision.tried)
        if not pool:
            return RoutingDecision(
                reason="no safe fallback within the data and locality policy",
                tried=decision.tried,
            )
        chosen_id = pool[0]
        tried = decision.tried + [chosen_id]
        return RoutingDecision(
            model_id=chosen_id,
            selected=True,
            reason=f"fallback from {decision.model_id} within {current.fallback_group}; same locality and data policy",
            matched_rules=decision.matched_rules,
            tried=tried,
            fallback_candidates=self._fallback_pool(self._registry.get(chosen_id), request, tried),
        )
