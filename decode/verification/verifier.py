"""Rule-based completion verifier for the agent loop.

Builds a completion context from the task state (latest observation plus derived
signals) and evaluates the objective-level completion conditions against it,
reusing :meth:`TaskState.evaluate_completion` (which reuses
:meth:`CompletionCriterion.check`). Completion conditions may reference these
context fields:

- ``last_success`` (bool) — did the most recent observation succeed?
- ``last_observation`` (dict) — the most recent observation's ``data``
  (e.g. ``last_observation.exit_code``, ``last_observation.stdout``).
- ``findings_count`` (int), ``findings`` (list[str] of titles)
- ``observations_count`` (int)
- ``status`` (str) — the current task status.

With no completion conditions declared, verification accepts (nothing to check).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..utils import parse_llm_response


class VerificationResult(BaseModel):
    valid: bool
    reasons: List[str] = Field(default_factory=list)
    failed_criteria: List[str] = Field(default_factory=list)


class Verifier:
    def build_context(
        self, task_state: Any, last_observation: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        observations = getattr(task_state, "observations", [])
        latest = observations[-1] if observations else None
        last_data = (
            (last_observation or {}).get("data")
            if last_observation is not None
            else (latest.data if latest is not None else {})
        ) or {}
        findings = getattr(task_state, "findings", [])
        return {
            "last_success": bool(latest.success) if latest is not None else False,
            "last_observation": last_data,
            "observations_count": len(observations),
            "findings_count": len(findings),
            "findings": [f.title for f in findings],
            "status": getattr(task_state.status, "value", str(task_state.status)),
        }

    def verify(
        self, task_state: Any, last_observation: Optional[Dict[str, Any]] = None
    ) -> VerificationResult:
        if not getattr(task_state, "completion_conditions", None):
            return VerificationResult(
                valid=True, reasons=["no completion conditions declared; accepting"]
            )
        context = self.build_context(task_state, last_observation)
        complete, failures = task_state.evaluate_completion(context)
        return VerificationResult(
            valid=complete,
            reasons=[] if complete else ["completion conditions not met"],
            failed_criteria=failures,
        )


_REVIEW_SYSTEM = """You are a strict reviewer. Given a task's objective and its recent
progress, decide whether the objective is actually met and it is sound to finish.
Consider: was the goal achieved, did tests pass, were regressions avoided, and is
every claim backed by an observation? Respond with a single JSON object and
nothing else: {"valid": true|false, "reasons": ["..."]}. Use valid:false when the
objective is not yet met."""


class ModelVerifier:
    """Reviewer-model verifier (subsystem 10).

    Layers a semantic model review on top of the deterministic completion gate:
    the rule-based :class:`Verifier` runs first (hard gate on declared completion
    conditions), and only if it passes does the reviewer model judge whether the
    objective is genuinely met. Fails open (accepts) when the model reply cannot be
    parsed, so review never deadlocks the bounded loop.
    """

    def __init__(self, provider: Any, rule_verifier: Optional[Verifier] = None) -> None:
        self._provider = provider
        self._rules = rule_verifier or Verifier()

    async def verify(
        self, task_state: Any, last_observation: Optional[Dict[str, Any]] = None
    ) -> VerificationResult:
        base = self._rules.verify(task_state, last_observation)
        if not base.valid:
            return base
        prompt = self._review_prompt(task_state, last_observation)
        try:
            raw = await self._provider.chat([
                {"role": "system", "content": _REVIEW_SYSTEM},
                {"role": "user", "content": prompt},
            ])
        except Exception:
            return VerificationResult(valid=True, reasons=["reviewer unavailable; accepting"])
        decision = parse_llm_response(raw)
        if "valid" not in decision:
            return VerificationResult(valid=True, reasons=["reviewer reply not parseable; accepting"])
        valid = bool(decision.get("valid"))
        reasons = [str(r) for r in (decision.get("reasons") or [])]
        if not valid and not reasons:
            reasons = ["reviewer judged the objective not yet met"]
        return VerificationResult(valid=valid, reasons=reasons)

    @staticmethod
    def _review_prompt(task_state: Any, last_observation: Optional[Dict[str, Any]]) -> str:
        parts = [task_state.render_compact()]
        if last_observation is not None:
            parts.append("Last observation: " + str(last_observation.get("summary", ""))[:400])
        parts.append('Reply with {"valid": true|false, "reasons": ["..."]}.')
        return "\n\n".join(parts)
