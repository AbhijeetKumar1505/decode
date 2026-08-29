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
