from enum import Enum
from functools import wraps
from typing import Dict, Any
from abc import ABC, abstractmethod


class RiskLevel(str, Enum):
    READ = "READ"  # Passive recon, reading files
    WRITE = "WRITE"  # Active scanning, non-destructive
    DESTRUCTIVE = "DESTRUCTIVE"  # Exploitation, potential system change


class Plugin(ABC):
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        implementation = cls.__dict__.get("execute")
        if implementation is None:
            return

        @wraps(implementation)
        def quarantined_execute(
            self: "Plugin",
            *args: Any,
            **execute_kwargs: Any,
        ) -> Any:
            raise RuntimeError(
                "Direct legacy plugin execution is disabled; use the registered "
                "skill through ExecutionCoordinator"
            )

        cls.execute = quarantined_execute

    def __init__(self):
        self.name: str = ""
        self.description: str = ""
        self.risk_level: RiskLevel = RiskLevel.READ
        self.schema: Dict[str, Any] = {}

    @abstractmethod
    def execute(self, **kwargs) -> Any:
        pass

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "risk_level": self.risk_level,
            "schema": self.schema,
        }
