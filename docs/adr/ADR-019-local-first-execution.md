# ADR-019: Preserve Local-First Execution

**Status:** Accepted

## Context

Security data is sensitive, internet access may be restricted, and individual researchers need a low-operations deployment.

## Decision

Keep the CLI, SQLite, filesystem evidence, and in-process orchestration as a supported first-class profile. Cloud/team services are optional.

## Consequences

- Users retain control and can work offline.
- Local resource and concurrency limits remain.
- Distributed features must degrade cleanly without weakening policy.
