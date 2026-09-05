"""Agent framework — the base for governed, capability-owning agents.

An agent owns a domain and a set of capabilities and executes a plan node inside
its coordinator-governed context. The only concrete agent today is
:class:`~decode.agents.host.HostAgent`, which handles ``internal`` host
capabilities; there is no longer a tool-resolving capability registry.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from ..execution.base import _execution_matches
from ..planner.dag import PlanNode

if TYPE_CHECKING:
    from .descriptor import AgentDescriptor


class AgentResult(BaseModel):
    agent: str
    capability: str
    success: bool
    summary: str = ""
    output: str = ""
    error: str = ""
    normalized: dict[str, Any] = Field(default_factory=dict)
    partial: bool = False
    warnings: list[str] = Field(default_factory=list)


class Agent(ABC):
    #: Domain label, e.g. "recon".
    domain: str = "generic"

    @property
    @abstractmethod
    def capabilities(self) -> list[str]:
        """Capabilities this agent can handle."""

    def handles(self, capability: str) -> bool:
        return capability in self.capabilities

    def descriptor(self) -> AgentDescriptor:
        """The versioned envelope that bounds this agent. Override to customize."""
        from .descriptor import descriptor_for_agent

        return descriptor_for_agent(self)

    async def run(
        self,
        node: PlanNode,
        registry: Any,
        context: dict | None = None,
    ) -> AgentResult:
        """Execute a plan node inside its matching coordinator context.

        ``registry`` need only resolve a capability spec (``get_spec``). Only
        ``internal`` capabilities are supported; there is no tool-resolution path.
        """
        if not _execution_matches(node.capability):
            raise RuntimeError(
                "Direct agent execution is disabled; use ExecutionCoordinator"
            )
        execution_context = context or {}
        spec = registry.get_spec(node.capability)

        if spec is not None and spec.kind == "internal":
            return await self.execute_internal(node, execution_context)

        return AgentResult(
            agent=self.domain,
            capability=node.capability,
            success=False,
            error=f"no handler for non-internal capability '{node.capability}'",
        )

    async def execute_internal(self, node: PlanNode, context: dict) -> AgentResult:
        """Handle an ``internal`` (non-tool) capability. Override in agents that
        declare internal capabilities (e.g. reporting, analysis)."""
        raise NotImplementedError(
            f"{self.domain} agent has no handler for internal capability '{node.capability}'"
        )
