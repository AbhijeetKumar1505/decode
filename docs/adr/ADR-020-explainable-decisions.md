# ADR-020: Record Explainable System Decisions

**Status:** Accepted

## Context

Users need to understand why Decode selected a capability, tool, model, policy outcome, or fallback. Hidden reasoning is unsuitable for audit.

## Decision

Record concise public reasons based on inputs, rules, health, versions, and scores. Do not expose or depend on private model chain-of-thought.

## Consequences

- Routing and policy behavior can be reviewed and reproduced.
- Decision schemas and reason codes require maintenance.
- Explanations must be faithful, redacted, and linked to evidence.
