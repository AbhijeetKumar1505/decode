"""Plan graph — a DAG of capability-typed steps.

Nodes carry capability intent, dependencies, completion criteria, and conservative
recovery metadata. They do not grant approval or execute tools.
"""

import hashlib
import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class CompletionCriterion(BaseModel):
    """A typed, evidence-oriented condition required before a node succeeds."""

    kind: str = Field(min_length=1, max_length=64)
    field: str = Field(default="", max_length=128)
    expected: Any = None
    required: bool = True

    def check(self, values: Any) -> tuple[bool, str]:
        """Evaluate this criterion against a result mapping.

        Returns ``(ok, reason)``. Non-required criteria always pass. Shared by
        :meth:`PlanGraph.validate_completion` (per-node) and the objective-level
        completion gate in the task-state schema.
        """
        if not self.required:
            return True, ""
        actual: Any = values if isinstance(values, dict) else {"value": values}
        if self.field:
            for part in self.field.split("."):
                if not isinstance(actual, dict) or part not in actual:
                    actual = None
                    break
                actual = actual[part]
        if self.kind == "equals" and actual != self.expected:
            return (
                False,
                f"completion criterion failed: {self.field} must equal expected value",
            )
        if self.kind == "present" and actual in (None, "", [], {}):
            return False, f"completion criterion failed: {self.field} is required"
        if self.kind not in {"equals", "present"}:
            return False, f"unsupported completion criterion: {self.kind}"
        return True, ""


class RetryCategory(str, Enum):
    NEVER = "never"
    TRANSIENT_READ = "transient_read"
    MANUAL_REVIEW = "manual_review"


class PlanNode(BaseModel):
    id: str
    capability: str
    description: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    completion: list[CompletionCriterion] = Field(default_factory=list)
    retry_category: RetryCategory = RetryCategory.NEVER
    max_attempts: int = Field(default=1, ge=1, le=3)
    idempotency_key: str = Field(default="", max_length=128)
    status: str = "pending"
    result_summary: str = ""

    @field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, value: str) -> str:
        if value and not value.replace("-", "").replace("_", "").isalnum():
            raise ValueError("idempotency_key must be an identifier")
        return value

    def material_fingerprint(self) -> str:
        """Hash fields whose change requires a fresh execution approval."""
        payload = {
            "capability": self.capability,
            "params": self.params,
            "completion": [item.model_dump() for item in self.completion],
            "retry_category": self.retry_category.value,
            "idempotency_key": self.idempotency_key,
        }
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class PlanGraph(BaseModel):
    goal: str = ""
    nodes: dict[str, PlanNode] = Field(default_factory=dict)
    reasoning: str = ""

    def add_node(self, node: PlanNode) -> PlanNode:
        self.nodes[node.id] = node
        return node

    def validate_edges(self) -> None:
        for node in self.nodes.values():
            for dep in node.depends_on:
                if dep not in self.nodes:
                    raise ValueError(
                        f"node '{node.id}' depends on unknown node '{dep}'"
                    )
        self.topological_order()

    def ready_nodes(self) -> list[PlanNode]:
        return [
            node
            for node in self.nodes.values()
            if node.status == "pending"
            and all(
                self.nodes[dependency].status == "success"
                for dependency in node.depends_on
            )
        ]

    def topological_order(self) -> list[PlanNode]:
        order: list[PlanNode] = []
        temporary, permanent = set(), set()

        def visit(node_id: str) -> None:
            if node_id in permanent:
                return
            if node_id in temporary:
                raise ValueError(f"cycle detected involving node '{node_id}'")
            temporary.add(node_id)
            for dependency in self.nodes[node_id].depends_on:
                visit(dependency)
            temporary.discard(node_id)
            permanent.add(node_id)
            order.append(self.nodes[node_id])

        for node_id in self.nodes:
            visit(node_id)
        return order

    def is_complete(self) -> bool:
        return all(
            node.status in ("success", "error", "skipped", "needs_review")
            for node in self.nodes.values()
        )

    def mark(self, node_id: str, status: str, summary: str = "") -> None:
        node = self.nodes[node_id]
        node.status = status
        if summary:
            node.result_summary = summary

    def validate_completion(self, node_id: str, result: Any) -> tuple[bool, str]:
        node = self.nodes[node_id]
        values = result.model_dump() if hasattr(result, "model_dump") else result
        if not isinstance(values, dict):
            values = {"value": values}
        for criterion in node.completion:
            ok, reason = criterion.check(values)
            if not ok:
                return False, reason
        return True, ""
