"""Model gateway — role-based provider selection (subsystem 01).

Maps agent roles (``planner``, ``worker``, ``reviewer``, ``coder``) to a concrete
LLM provider. Single-model is the default: unless a per-role override
(``DECODE_<ROLE>_MODEL``) is set, or routing is opted into
(``DECODE_MODEL_ROUTING=1``), every role resolves to the configured
``Config.PROVIDER`` / ``Config.MODEL`` — the same provider the loop uses today.
When routing is enabled the already-built :class:`ModelRouter` picks the model
per role's task class; providers are instantiated through the existing
``create_provider`` and cached.
"""

from __future__ import annotations

import os
from typing import Dict, Tuple

from ..config import Config
from ..kernel.provider import LLMProvider, create_provider
from .registry import ModelRegistry
from .routing import ModelRouter, RoutingDecision, RoutingRequest

_ROLE_TASK_CLASS: Dict[str, str] = {
    "planner": "planning",
    "worker": "analysis",
    "reviewer": "analysis",
    "coder": "code",
}
_ROLE_ENV: Dict[str, str] = {
    "planner": "DECODE_PLANNER_MODEL",
    "worker": "DECODE_WORKER_MODEL",
    "reviewer": "DECODE_REVIEWER_MODEL",
    "coder": "DECODE_CODER_MODEL",
}
_KNOWN_PROVIDERS = {"openrouter", "openai", "anthropic"}


def _routing_default() -> bool:
    return os.getenv("DECODE_MODEL_ROUTING", "").strip().lower() in {"1", "true", "yes"}


class ModelGateway:
    def __init__(
        self,
        registry: ModelRegistry,
        router: ModelRouter | None = None,
        *,
        routing_enabled: bool | None = None,
    ) -> None:
        self._registry = registry
        self._router = router or ModelRouter(registry)
        self._routing_enabled = _routing_default() if routing_enabled is None else routing_enabled
        self._cache: Dict[Tuple[str, str], LLMProvider] = {}

    def register(self, provider_name: str, model_name: str, provider: LLMProvider) -> None:
        """Seed a pre-built provider (e.g. the agent's default llm) so the default
        role resolution returns the same instance and preserves its token accounting."""
        self._cache[(provider_name, model_name)] = provider

    def route_for_role(self, role: str, **constraints) -> RoutingDecision:
        task_class = _ROLE_TASK_CLASS.get(role, "analysis")
        return self._router.route(RoutingRequest(task_class=task_class, **constraints))

    def resolve_spec(self, role: str) -> Tuple[str, str]:
        """Return ``(provider_name, model_name)`` for a role."""
        override = os.getenv(_ROLE_ENV.get(role, ""), "").strip()
        if override:
            spec = self._registry.get(override)
            if spec is not None:
                return spec.provider, spec.model_name
            if "/" in override:
                prefix, rest = override.split("/", 1)
                if prefix in _KNOWN_PROVIDERS:
                    return prefix, rest
            return Config.PROVIDER, override
        if self._routing_enabled:
            decision = self.route_for_role(role)
            if decision.selected and decision.model_id:
                spec = self._registry.get(decision.model_id)
                if spec is not None:
                    return spec.provider, spec.model_name
        return Config.PROVIDER, Config.MODEL

    def for_role(self, role: str) -> LLMProvider:
        provider_name, model_name = self.resolve_spec(role)
        key = (provider_name, model_name)
        if key not in self._cache:
            self._cache[key] = create_provider(provider_name, model=model_name)
        return self._cache[key]
