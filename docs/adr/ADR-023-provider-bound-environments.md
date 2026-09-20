# ADR-023: Bind Discovery and Execution to One Environment Provider

**Status:** Accepted

## Decision

EnvironmentProvider owns identity, discovery, health, cwd/filesystem semantics,
and execution. A discovered tool runs only through that provider unless
re-resolved.

## Consequences

Local/WSL/Docker/SSH/MCP need conformance. Paths are not portable. Provider drift
invalidates approval/replay.
