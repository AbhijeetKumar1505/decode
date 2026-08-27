# ADR-015: Bind Human Confirmation to the Material Action

**Status:** Accepted

## Context

Generic confirmation prompts do not give users enough information and can be replayed after a plan changes.

## Decision

Present target, action, tool, executor, side effects, data use, and risk. Bind approval to a digest and expiry. Material changes require fresh approval.

## Consequences

- User control and auditability improve.
- Approval records need identity, integrity, and lifecycle management.
- Chat text alone is not an approval token.
