"""Neural Schema — the live task-state representation (subsystem 04).

`TaskState` is the structured world-state the agent loop reads and writes each
turn, instead of relying solely on the raw message history. It carries the
objective, scope, hypotheses, plan (a reused ``PlanGraph``), actions,
observations, findings, open questions, and completion conditions.
"""

from .task_state import (
    ActionRecord,
    Artifact,
    Finding,
    Hypothesis,
    Observation,
    ScopeView,
    TaskMode,
    TaskState,
    TaskStatus,
)

__all__ = [
    "ActionRecord",
    "Artifact",
    "Finding",
    "Hypothesis",
    "Observation",
    "ScopeView",
    "TaskMode",
    "TaskState",
    "TaskStatus",
]
