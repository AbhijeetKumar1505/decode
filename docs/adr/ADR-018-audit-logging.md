# ADR-018: Make Security Audit Events Mandatory

**Status:** Accepted

## Decision

Record append-only versioned events for policy, approval, execution, finding,
evidence, memory, extension, and state. Consequential work fails closed if audit
cannot commit. Raw evidence is separate.

## Consequences

Retention, integrity, redaction, access, export, and correlation are required.
Audit is not secret storage or memory.
