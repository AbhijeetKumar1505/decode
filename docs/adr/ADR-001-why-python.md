# ADR-001: Python Runtime Core and TypeScript CLI

**Status:** Accepted; amended for v2

## Context

The security/execution/evidence/model/storage core is Python. The target terminal
UX benefits from TypeScript.

## Decision

Use Python 3.12+ target with typing/Pydantic for runtime. Keep current Python CLI
during migration. After stable local API contracts, build TypeScript/Node CLI as
a client; it never imports Python internals.

## Consequences

Runtime stays cohesive and avoids rewrite. Two toolchains/shared schemas need CI.
Python CLI removal requires parity, rollback, and compatibility releases.
