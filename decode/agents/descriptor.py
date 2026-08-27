"""Versioned agent descriptors and least-privilege delegation.

A descriptor is the declarative envelope that constrains an agent: the
capabilities it may request, its maximum risk, the memory it may read and write,
the model capabilities it needs, and its execution budget. Descriptors never
grant authority beyond project policy — they only narrow it. Delegation derives
a child descriptor that is a strict subset of its parent so a delegated agent can
never broaden scope, risk, memory access, or budget.
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..skills.base import RiskLevel

DESCRIPTOR_SCHEMA_VERSION = 1

# READ < WRITE < DESTRUCTIVE
_RISK_ORDER = {RiskLevel.READ: 0, RiskLevel.WRITE: 1, RiskLevel.DESTRUCTIVE: 2}


def risk_at_most(candidate: RiskLevel, ceiling: RiskLevel) -> bool:
    return _RISK_ORDER[candidate] <= _RISK_ORDER[ceiling]


def max_risk(risks: List[RiskLevel]) -> RiskLevel:
    return max(risks, key=lambda r: _RISK_ORDER[r]) if risks else RiskLevel.READ


class AgentPermissions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    maximum_risk: RiskLevel = RiskLevel.READ
    network: str = "scoped-targets"


class AgentMemoryScopes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read: List[str] = Field(default_factory=list)
    write: List[str] = Field(default_factory=list)


class AgentModelRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_capabilities: List[str] = Field(default_factory=list)
    max_data_classification: str = "internal"
    pinned_model: str = ""


class AgentLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeout_seconds: int = Field(default=900, ge=1, le=86_400)
    retries: int = Field(default=1, ge=0, le=5)
    token_budget: int = Field(default=100_000, ge=0)
    max_delegation_depth: int = Field(default=1, ge=0, le=4)


class AgentDescriptor(BaseModel):
    """The validated, versioned envelope that bounds an agent."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    version: int = Field(default=DESCRIPTOR_SCHEMA_VERSION, ge=1)
    purpose: str = ""
    capabilities: List[str] = Field(default_factory=list)
    permissions: AgentPermissions = Field(default_factory=AgentPermissions)
    allow_capabilities: List[str] = Field(default_factory=list)
    memory: AgentMemoryScopes = Field(default_factory=AgentMemoryScopes)
    models: AgentModelRequirements = Field(default_factory=AgentModelRequirements)
    limits: AgentLimits = Field(default_factory=AgentLimits)

    @model_validator(mode="after")
    def _validate_envelope(self) -> "AgentDescriptor":
        if not self.allow_capabilities:
            object.__setattr__(self, "allow_capabilities", list(self.capabilities))
        unlisted = set(self.capabilities) - set(self.allow_capabilities)
        if unlisted:
            raise ValueError(
                f"capabilities not permitted by allow_capabilities: {sorted(unlisted)}"
            )
        return self

    def permits(self, capability: str) -> bool:
        return capability in self.allow_capabilities

    def delegate(
        self,
        child_id: str,
        capabilities: List[str],
        *,
        maximum_risk: RiskLevel | None = None,
        token_budget: int | None = None,
        memory_read: List[str] | None = None,
        memory_write: List[str] | None = None,
    ) -> "AgentDescriptor":
        """Derive a child descriptor as a strict subset of this one.

        Raises ``ValueError`` if the child would broaden capabilities, risk,
        memory access, budget, or exceed the remaining delegation depth.
        """
        if self.limits.max_delegation_depth <= 0:
            raise ValueError("this descriptor may not delegate further")

        requested = list(dict.fromkeys(capabilities))
        broadened = set(requested) - set(self.allow_capabilities)
        if broadened:
            raise ValueError(f"delegation cannot add capabilities: {sorted(broadened)}")

        child_risk = maximum_risk or self.permissions.maximum_risk
        if not risk_at_most(child_risk, self.permissions.maximum_risk):
            raise ValueError("delegation cannot raise maximum risk")

        child_budget = self.limits.token_budget if token_budget is None else token_budget
        if child_budget > self.limits.token_budget:
            raise ValueError("delegation cannot raise the token budget")

        read = self.memory.read if memory_read is None else memory_read
        write = self.memory.write if memory_write is None else memory_write
        if set(read) - set(self.memory.read):
            raise ValueError("delegation cannot add memory read scopes")
        if set(write) - set(self.memory.write):
            raise ValueError("delegation cannot add memory write scopes")

        return AgentDescriptor(
            id=child_id,
            version=self.version,
            purpose=f"delegated by {self.id}",
            capabilities=requested,
            permissions=AgentPermissions(
                maximum_risk=child_risk, network=self.permissions.network
            ),
            allow_capabilities=requested,
            memory=AgentMemoryScopes(read=list(read), write=list(write)),
            models=self.models.model_copy(),
            limits=AgentLimits(
                timeout_seconds=self.limits.timeout_seconds,
                retries=self.limits.retries,
                token_budget=child_budget,
                max_delegation_depth=self.limits.max_delegation_depth - 1,
            ),
        )


def descriptor_for_agent(agent: object) -> AgentDescriptor:
    """Build the default descriptor for a shipped agent from its capabilities.

    ``maximum_risk`` is computed from the registered risk of the agent's
    capabilities so the envelope can never under-declare what the agent may do.
    """
    from ..capabilities import CAPABILITIES

    capabilities = list(getattr(agent, "capabilities"))
    risks = [
        CAPABILITIES[name].risk for name in capabilities if name in CAPABILITIES
    ]
    return AgentDescriptor(
        id=getattr(agent, "domain", "generic"),
        purpose=(agent.__doc__ or "").strip().split("\n")[0][:200],
        capabilities=capabilities,
        permissions=AgentPermissions(maximum_risk=max_risk(risks)),
        allow_capabilities=capabilities,
        memory=AgentMemoryScopes(
            read=["session", "project"], write=["project", "evidence"]
        ),
        models=AgentModelRequirements(required_capabilities=["structured_output"]),
    )
