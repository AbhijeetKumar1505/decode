# ADR-026: Defer AWS Until Local v2 Release Gates Pass

**Status:** Accepted

## Decision

Complete Linux, Kali WSL, and Docker gates first. Design AWS only after project
creation and local conformance, migration, security, and benchmark evidence.

## Consequences

Account, region, services, networking, and IaC remain unspecified. The future
cloud RFC maps stable contracts and cannot weaken local-first operation.
