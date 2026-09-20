# ADR-014: Authorize the Exact Resolved Action

**Status:** Accepted; amended for v2

## Decision

Resolve exact action, then classify side effects and enforce target/network/
filesystem-output/credential/provider/risk/approval immediately before execution.
Unknown effects fail closed.

## Consequences

Adapters expose risk facts; output options cannot hide writes; provider identity
is policy input. Material changes invalidate approval.
