# ADR-018: Make Audit Logging Mandatory

**Status:** Accepted

## Context

Security work must preserve who authorized and performed which action against what target and with what outcome.

## Decision

Every skill execution produces structured execution logging, a security audit event, and execution feedback. Consequential work fails closed if mandatory audit cannot be recorded.

## Consequences

- Investigations and failures become traceable.
- Logs require integrity, retention, redaction, and access controls.
- Audit data must not become a second secret store.
