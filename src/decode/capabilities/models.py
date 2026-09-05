"""Capability taxonomy — the vocabulary the planner/agents speak instead of
naming tools. Each capability names an intent (e.g. ``port_scan``), a risk
level (reusing the skill RiskLevel so governance can gate it), and an ordered
preference of catalog tools that can satisfy it. Which of those tools actually
run is decided at execution time from what discovery (F2) found.
"""

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from ..skills.base import RiskLevel

CAPABILITY_SCHEMA_VERSION = "1.0.0"
ARGUMENT_SCHEMA_VERSION = "1.0.0"
RESULT_SCHEMA_VERSION = "1.0.0"
PARSER_SCHEMA_VERSION = "1.0.0"
_SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


class ArgumentType(str, Enum):
    STRING = "string"
    TARGET = "target"
    URL = "url"
    DOMAIN = "domain"
    PORT_RANGE = "port_range"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    ENUM = "enum"
    PATH = "path"


class CapabilityArgument(BaseModel):
    type: ArgumentType
    description: str = ""
    required: bool = False
    default: Any = None
    choices: list[str] = Field(default_factory=list)
    minimum: int | None = None
    maximum: int | None = None
    max_length: int = Field(default=2048, ge=1, le=65536)
    sensitive: bool = False

    @model_validator(mode="after")
    def validate_contract(self) -> "CapabilityArgument":
        if self.type == ArgumentType.ENUM and not self.choices:
            raise ValueError("enum arguments require choices")
        if self.minimum is not None and self.maximum is not None:
            if self.minimum > self.maximum:
                raise ValueError("argument minimum cannot exceed maximum")
        return self


class CapabilityResultField(BaseModel):
    type: str
    description: str = ""
    required: bool = True


_TARGET_ARGUMENT = CapabilityArgument(
    type=ArgumentType.TARGET,
    description="Authorized IP address, hostname, URL, or CIDR target",
    required=True,
)
_OPTIONAL_TARGET_ARGUMENT = _TARGET_ARGUMENT.model_copy(update={"required": False})
_PORT_ARGUMENT = CapabilityArgument(
    type=ArgumentType.PORT_RANGE,
    description="Comma-separated ports or inclusive port ranges",
    required=False,
)
_ARGUMENT_SCHEMAS: dict[str, dict[str, CapabilityArgument]] = {
    "host_discovery": {"target": _TARGET_ARGUMENT},
    "port_scan": {
        "target": _TARGET_ARGUMENT,
        "ports": _PORT_ARGUMENT,
        "timing": CapabilityArgument(
            type=ArgumentType.ENUM,
            choices=["safe", "normal", "fast"],
            default="normal",
        ),
        "service_detection": CapabilityArgument(
            type=ArgumentType.BOOLEAN,
            default=False,
        ),
        "default_scripts": CapabilityArgument(
            type=ArgumentType.BOOLEAN,
            default=False,
        ),
        "os_detection": CapabilityArgument(
            type=ArgumentType.BOOLEAN,
            default=False,
        ),
        "reason": CapabilityArgument(
            type=ArgumentType.BOOLEAN,
            default=False,
        ),
        "rate": CapabilityArgument(
            type=ArgumentType.INTEGER,
            minimum=1,
            maximum=10000,
            default=1000,
        ),
    },
    "service_detection": {"target": _TARGET_ARGUMENT, "ports": _PORT_ARGUMENT},
    "os_detection": {"target": _TARGET_ARGUMENT, "ports": _PORT_ARGUMENT},
    "http_fingerprint": {
        "target": _TARGET_ARGUMENT,
        "url": CapabilityArgument(type=ArgumentType.URL, required=False),
        "aggressive": CapabilityArgument(
            type=ArgumentType.BOOLEAN,
            default=False,
        ),
    },
    "http_probe": {
        "target": _TARGET_ARGUMENT,
        "url": CapabilityArgument(type=ArgumentType.URL, required=False),
    },
    "dir_enum": {
        "target": _TARGET_ARGUMENT,
        "url": CapabilityArgument(type=ArgumentType.URL, required=False),
        "wordlist": CapabilityArgument(type=ArgumentType.PATH, required=False),
        "extensions": CapabilityArgument(type=ArgumentType.STRING, required=False),
        "threads": CapabilityArgument(
            type=ArgumentType.INTEGER,
            minimum=1,
            maximum=100,
            default=20,
        ),
    },
    "vuln_scan": {
        "target": _TARGET_ARGUMENT,
        "url": CapabilityArgument(type=ArgumentType.URL, required=False),
    },
    "sql_injection": {
        "target": _TARGET_ARGUMENT,
        "url": CapabilityArgument(type=ArgumentType.URL, required=False),
    },
    "subdomain_enum": {
        "target": _TARGET_ARGUMENT,
        "domain": CapabilityArgument(type=ArgumentType.DOMAIN, required=False),
    },
    "osint": {
        "target": _TARGET_ARGUMENT,
        "domain": CapabilityArgument(type=ArgumentType.DOMAIN, required=False),
    },
    "ad_enum": {"target": _TARGET_ARGUMENT},
    "smb_enum": {"target": _TARGET_ARGUMENT},
    "password_attack": {"target": _TARGET_ARGUMENT},
    "password_cracking": {
        "target": _OPTIONAL_TARGET_ARGUMENT,
        "hash_file": CapabilityArgument(type=ArgumentType.PATH, required=False),
    },
    "exploit_search": {
        "target": _OPTIONAL_TARGET_ARGUMENT,
        "query": CapabilityArgument(type=ArgumentType.STRING, required=False),
    },
    "report": {
        "formats": CapabilityArgument(type=ArgumentType.STRING, required=False),
    },
    "log_analysis": {
        "path": CapabilityArgument(type=ArgumentType.PATH, required=False),
    },
    "detection_test": {"target": _TARGET_ARGUMENT},
    "hardening_check": {"target": _TARGET_ARGUMENT},
    # ── host control (general OS operations; executed internally) ──
    "file_read": {"path": CapabilityArgument(type=ArgumentType.PATH, required=True)},
    "file_list": {"path": CapabilityArgument(type=ArgumentType.PATH, required=True)},
    "file_search": {
        "root": CapabilityArgument(type=ArgumentType.PATH, required=True),
        "pattern": CapabilityArgument(type=ArgumentType.STRING, required=True),
        "glob": CapabilityArgument(type=ArgumentType.STRING, required=False),
    },
    "file_write": {
        "path": CapabilityArgument(type=ArgumentType.PATH, required=True),
        "content": CapabilityArgument(
            type=ArgumentType.STRING, required=True, max_length=65536
        ),
    },
    "file_edit": {
        "path": CapabilityArgument(type=ArgumentType.PATH, required=True),
        "old": CapabilityArgument(
            type=ArgumentType.STRING, required=True, max_length=65536
        ),
        "new": CapabilityArgument(
            type=ArgumentType.STRING, required=True, max_length=65536
        ),
    },
    "file_fetch": {
        "source": CapabilityArgument(type=ArgumentType.PATH, required=True),
        "dest": CapabilityArgument(type=ArgumentType.PATH, required=True),
    },
    "process_list": {},
    "process_kill": {
        "pid": CapabilityArgument(type=ArgumentType.INTEGER, required=True, minimum=1)
    },
    "service_status": {
        "name": CapabilityArgument(type=ArgumentType.STRING, required=True)
    },
    "service_control": {
        "name": CapabilityArgument(type=ArgumentType.STRING, required=True),
        "action": CapabilityArgument(
            type=ArgumentType.ENUM, choices=["start", "stop", "restart"], required=True
        ),
    },
    "shell_command": {
        "command": CapabilityArgument(
            type=ArgumentType.STRING, required=True, max_length=8192
        )
    },
    "host_session": {
        "commands": CapabilityArgument(
            type=ArgumentType.STRING, required=True, max_length=16384
        )
    },
}
_RESULT_SCHEMA = {
    "normalized": CapabilityResultField(
        type="json",
        description="Capability-normalized result data",
    ),
    "partial": CapabilityResultField(
        type="boolean",
        description="Whether parsing or collection was incomplete",
    ),
    "warnings": CapabilityResultField(
        type="list[string]",
        description="Non-fatal parser and compatibility warnings",
    ),
    "raw_evidence": CapabilityResultField(
        type="evidence_reference",
        description="Protected immutable raw-output reference",
    ),
}


class CapabilitySpec(BaseModel):
    schema_version: str = CAPABILITY_SCHEMA_VERSION
    arguments_schema_version: str = ARGUMENT_SCHEMA_VERSION
    result_schema_version: str = RESULT_SCHEMA_VERSION
    parser_schema_version: str = PARSER_SCHEMA_VERSION
    name: str
    description: str
    category: str
    risk: RiskLevel = RiskLevel.WRITE
    # "tool"     -> satisfied by a discovered tool via the CapabilityRegistry
    # "internal" -> satisfied by an agent's own Python logic (no tool/provider)
    kind: str = "tool"
    # Secure default: tool-backed capabilities must identify the scoped target.
    target_required: bool = True
    required_privileges: list[str] = Field(default_factory=lambda: ["user"])
    arguments_schema: dict[str, CapabilityArgument] = Field(default_factory=dict)
    result_schema: dict[str, CapabilityResultField] = Field(default_factory=dict)
    # Ordered tool preference; first available (per discovery) wins.
    preferred_tools: list[str] = Field(default_factory=list)

    @field_validator(
        "schema_version",
        "arguments_schema_version",
        "result_schema_version",
        "parser_schema_version",
    )
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        if not _SEMVER_PATTERN.fullmatch(value):
            raise ValueError("schema versions must use MAJOR.MINOR.PATCH")
        return value

    @model_validator(mode="after")
    def populate_schemas(self) -> "CapabilitySpec":
        if not self.arguments_schema:
            self.arguments_schema = {
                key: value.model_copy(deep=True)
                for key, value in _ARGUMENT_SCHEMAS.get(self.name, {}).items()
            }
        if not self.result_schema:
            self.result_schema = {
                key: value.model_copy(deep=True)
                for key, value in _RESULT_SCHEMA.items()
            }
        return self

    def normalize_params(self, params: dict[str, Any]) -> dict[str, Any]:
        unknown = sorted(set(params) - set(self.arguments_schema))
        if unknown:
            raise ValueError(f"unsupported normalized arguments: {', '.join(unknown)}")

        normalized: dict[str, Any] = {}
        for name, argument in self.arguments_schema.items():
            if name not in params or params[name] in (None, ""):
                if argument.required:
                    alternatives_satisfied = name == "target" and any(
                        params.get(key) for key in ("url", "domain")
                    )
                    if not alternatives_satisfied:
                        raise ValueError(
                            f"missing required normalized argument: {name}"
                        )
                if argument.default is not None:
                    normalized[name] = argument.default
                continue
            normalized[name] = self._normalize_value(name, params[name], argument)
        aliases = [
            normalized[key] for key in ("target", "url", "domain") if key in normalized
        ]
        if len(set(aliases)) > 1:
            raise ValueError("normalized target aliases conflict")
        return normalized

    @staticmethod
    def _normalize_value(
        name: str,
        value: Any,
        argument: CapabilityArgument,
    ) -> Any:
        if argument.type == ArgumentType.BOOLEAN:
            if not isinstance(value, bool):
                raise ValueError(f"normalized argument '{name}' must be boolean")
            return value
        if argument.type == ArgumentType.INTEGER:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"normalized argument '{name}' must be an integer")
            if argument.minimum is not None and value < argument.minimum:
                raise ValueError(f"normalized argument '{name}' is below its minimum")
            if argument.maximum is not None and value > argument.maximum:
                raise ValueError(f"normalized argument '{name}' exceeds its maximum")
            return value
        if not isinstance(value, str):
            raise ValueError(f"normalized argument '{name}' must be a string")
        text = value.strip()
        if not text or "\x00" in text or "\n" in text or "\r" in text:
            raise ValueError(f"normalized argument '{name}' contains invalid text")
        if len(text) > argument.max_length:
            raise ValueError(f"normalized argument '{name}' exceeds its maximum length")
        if argument.type == ArgumentType.ENUM and text not in argument.choices:
            raise ValueError(
                f"normalized argument '{name}' must be one of: "
                f"{', '.join(argument.choices)}"
            )
        if argument.type == ArgumentType.PORT_RANGE:
            CapabilitySpec._validate_port_range(name, text)
        return text

    @staticmethod
    def _validate_port_range(name: str, value: str) -> None:
        for segment in value.split(","):
            bounds = segment.split("-", 1)
            if not all(bound.isdigit() for bound in bounds):
                raise ValueError(
                    f"normalized argument '{name}' has an invalid port range"
                )
            ports = [int(bound) for bound in bounds]
            if any(port < 1 or port > 65535 for port in ports):
                raise ValueError(
                    f"normalized argument '{name}' has a port outside 1-65535"
                )
            if len(ports) == 2 and ports[0] > ports[1]:
                raise ValueError(f"normalized argument '{name}' has a descending range")


# Canonical capability set. Only first-class **host** capabilities remain — all
# agent-executed internal operations (files, processes, services, tool discovery,
# ad-hoc commands, sessions). There is no hardcoded external-tool taxonomy: the
# universal agent discovers installed tools (list_tools) and runs any of them
# through the governed shell_command capability. The capability → MITRE ATT&CK
# vocabulary lives in decode/knowledge/attack_map.py, independent of this set.
CAPABILITIES: dict[str, CapabilitySpec] = {
    # ── host control (first-class general OS operations; agent-executed, no external tool) ──
    "file_read": CapabilitySpec(
        name="file_read",
        description="Read a file within the authorized filesystem scope",
        category="host",
        risk=RiskLevel.READ,
        kind="internal",
        target_required=False,
    ),
    "file_list": CapabilitySpec(
        name="file_list",
        description="List a directory within the authorized scope",
        category="host",
        risk=RiskLevel.READ,
        kind="internal",
        target_required=False,
    ),
    "file_search": CapabilitySpec(
        name="file_search",
        description="Search files for a pattern within scope",
        category="host",
        risk=RiskLevel.READ,
        kind="internal",
        target_required=False,
    ),
    "file_write": CapabilitySpec(
        name="file_write",
        description="Write a file within the writable scope",
        category="host",
        risk=RiskLevel.WRITE,
        kind="internal",
        target_required=False,
    ),
    "file_edit": CapabilitySpec(
        name="file_edit",
        description="Replace text in a file within the writable scope",
        category="host",
        risk=RiskLevel.WRITE,
        kind="internal",
        target_required=False,
    ),
    "file_fetch": CapabilitySpec(
        name="file_fetch",
        description="Copy or stage a file between scoped paths",
        category="host",
        risk=RiskLevel.WRITE,
        kind="internal",
        target_required=False,
    ),
    "list_tools": CapabilitySpec(
        name="list_tools",
        description="List command-line tools installed on this host (optionally filtered)",
        category="host",
        risk=RiskLevel.READ,
        kind="internal",
        target_required=False,
    ),
    "process_list": CapabilitySpec(
        name="process_list",
        description="List running processes",
        category="host",
        risk=RiskLevel.READ,
        kind="internal",
        target_required=False,
    ),
    "process_kill": CapabilitySpec(
        name="process_kill",
        description="Terminate a process by PID",
        category="host",
        risk=RiskLevel.DESTRUCTIVE,
        kind="internal",
        target_required=False,
    ),
    "service_status": CapabilitySpec(
        name="service_status",
        description="Query a system service state",
        category="host",
        risk=RiskLevel.READ,
        kind="internal",
        target_required=False,
    ),
    "service_control": CapabilitySpec(
        name="service_control",
        description="Start, stop, or restart a system service",
        category="host",
        risk=RiskLevel.DESTRUCTIVE,
        kind="internal",
        target_required=False,
    ),
    "shell_command": CapabilitySpec(
        name="shell_command",
        description="Run a policy-checked argument-vector command",
        category="host",
        risk=RiskLevel.WRITE,
        kind="internal",
        target_required=False,
    ),
    "host_session": CapabilitySpec(
        name="host_session",
        description="Run a sequence of commands in a stateful session",
        category="host",
        risk=RiskLevel.WRITE,
        kind="internal",
        target_required=False,
    ),
}
