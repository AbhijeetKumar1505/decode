# ADR-019: Preserve Local-First Execution

**Status:** Accepted

## Decision

Keep Linux/WSL/Docker local execution, SQLite, filesystem evidence, and local
orchestration first class. Cloud/team services are optional profiles.

## Consequences

Local limits are explicit. Distributed features preserve contracts/degrade
cleanly. AWS is not required for core workflows.
