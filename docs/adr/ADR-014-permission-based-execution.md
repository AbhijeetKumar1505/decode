# ADR-014: Require Permission-Based Execution

**Status:** Accepted

## Context

Security tools can interact with targets, alter systems, use credentials, and cause disruption. Model intent is not a sufficient control.

## Decision

Classify capabilities as READ, WRITE, or DESTRUCTIVE and evaluate scope, resolved action, policy, and approval immediately before execution.

## Consequences

- Unsafe and out-of-scope actions fail closed.
- Adapters must expose argument-sensitive risk facts.
- More workflows pause for approval, which is an intentional safety cost.
