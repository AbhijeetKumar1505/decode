# ADR-021: Runtime Authority with Core and Active Brains

**Status:** Accepted

## Decision

Models provide cognition; runtime code is authority. Core owns workflow/DAG/
criteria/material replan; Active executes one authorized node and escalates
authority changes. Runtime owns policy/state/execution/verification.

## Consequences

Typed brain/escalation contracts are required. Core need not run for each tool.
Universal loop becomes Active migration source, not final architecture.
