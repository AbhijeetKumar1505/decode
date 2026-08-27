from enum import Enum
from functools import wraps
from typing import Dict, Any, List
from abc import ABC, abstractmethod
from pydantic import BaseModel, Field

from ..execution.base import _execution_matches


SCOPED_TARGET_FIELDS = frozenset(
    {
        "target",
        "url",
        "domain",
        "host",
        "hostname",
        "ip",
        "address",
        "cidr",
        "network",
    }
)


class RiskLevel(str, Enum):
    READ = "READ"
    WRITE = "WRITE"
    DESTRUCTIVE = "DESTRUCTIVE"


class DependencyKind(str, Enum):
    BINARY = "binary"
    PYTHON_PACKAGE = "python_package"


class SkillCategory(str, Enum):
    AI_SECURITY = "ai_security"
    APPLICATION_SECURITY = "application_security"
    INFRASTRUCTURE_SECURITY = "infrastructure_security"
    THREAT_INTELLIGENCE = "threat_intelligence"
    MALWARE_RESEARCH = "malware_research"
    REPORTING = "reporting"
    RECONNAISSANCE = "reconnaissance"
    EXPLOITATION = "exploitation"
    SOCIAL_IR = "social_ir"
    HOST_PROFILING = "host_profiling"
    NETWORK_MAPPING = "network_mapping"
    WEB_SCANNING = "web_scanning"
    EVIDENCE_MANAGEMENT = "evidence_management"
    AGENT_CORE = "agent_core"
    PHISHING_ANALYSIS = "phishing_analysis"
    CREDENTIAL_MONITORING = "credential_monitoring"
    MALWARE_INTELLIGENCE = "malware_intelligence"
    TIMELINE_ANALYSIS = "timeline_analysis"
    CLOUD_SECURITY = "cloud_security"
    AD_ENUMERATION = "ad_enumeration"
    K8S_AUDIT = "k8s_audit"
    ATTACK_GRAPH = "attack_graph"


class SkillIO(BaseModel):
    type: str = Field(description="Data type: string, integer, json, file, etc.")
    description: str = ""
    required: bool = True


class DependencyOption(BaseModel):
    name: str = Field(min_length=1)
    kind: DependencyKind = DependencyKind.BINARY
    install_name: str = ""


class DependencyCondition(BaseModel):
    parameter: str = Field(min_length=1)
    values: List[Any] = Field(default_factory=list)
    excluded_values: List[Any] = Field(default_factory=list)
    default: Any = None

    def matches(self, params: Dict[str, Any]) -> bool:
        value = params.get(self.parameter, self.default)
        if self.values and value not in self.values:
            return False
        return not self.excluded_values or value not in self.excluded_values


class SkillDependency(BaseModel):
    alternatives: List[DependencyOption] = Field(min_length=1)
    conditions: List[DependencyCondition] = Field(default_factory=list)

    def applies(self, params: Dict[str, Any]) -> bool:
        return all(condition.matches(params) for condition in self.conditions)

    @property
    def label(self) -> str:
        return " or ".join(option.name for option in self.alternatives)


class SkillSpec(BaseModel):
    name: str
    description: str
    category: SkillCategory
    risk_level: RiskLevel
    input_schema: Dict[str, SkillIO] = Field(default_factory=dict)
    output_schema: Dict[str, SkillIO] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    dependencies: List[SkillDependency] = Field(default_factory=list)
    required_privileges: List[str] = Field(default_factory=lambda: ["user"])
    requires_approval: bool = True
    target_required: bool | None = None

    def requires_scoped_target(self) -> bool:
        if self.target_required is not None:
            return self.target_required
        return any(
            name in SCOPED_TARGET_FIELDS and field.required
            for name, field in self.input_schema.items()
        )


class Skill(ABC):
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        implementation = cls.__dict__.get("execute")
        if implementation is None:
            return

        @wraps(implementation)
        async def governed_execute(
            self: "Skill",
            *args: Any,
            **execute_kwargs: Any,
        ) -> Dict[str, Any]:
            if not _execution_matches(self.spec.name):
                raise RuntimeError(
                    "Direct skill execution is disabled; use ExecutionCoordinator"
                )
            return await implementation(self, *args, **execute_kwargs)

        cls.execute = governed_execute

    def __init__(self):
        self.spec = self._build_spec()

    @abstractmethod
    def _build_spec(self) -> SkillSpec:
        pass

    @abstractmethod
    async def execute(self, **kwargs) -> Dict[str, Any]:
        pass

    def to_dict(self) -> Dict[str, Any]:
        return self.spec.model_dump()
