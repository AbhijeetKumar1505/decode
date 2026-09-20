# Pre-AWS Engineering Roadmap

**Status:** Binding local gates; details in [BUILD_PLAN.md](BUILD_PLAN.md)

## Goal

Prove v2 locally before cloud infrastructure. AWS must scale stable contracts,
not shortcut unfinished architecture.

## Gates

| Gate | Deliverable |
|---|---|
| 0 | truthful/safe execution |
| 1 | stable provider-bound kernel |
| 2 | Active Brain |
| 3 | Core Brain |
| 4 | workflow v2 |
| 5 | DAG + FSM |
| 6 | evidence/findings/memory |
| 7 | UTOS |
| 8 | local API + TypeScript CLI |
| 9 | deep security workflows |
| 10 | evaluation/distribution/conformance |

## Immediate backlog

Fix non-zero success, strict tool schemas, vector-mode metacharacters,
side-effect/output scope, provider-bound discovery/execution, exact discovery,
and governed HTTP/browser/search. Add the Bugcrowd/curl transcript regression.

## Every gate requires

Tests for normal/failure/denial/timeout/cancel/resume, state migration/rollback,
docs/ADR updates, one coordinator, evidence/audit, secret-safe fixtures, and an
updated continuation ledger.

## Platform matrix

Native Linux, explicit Kali/other WSL, scoped Docker, offline core, and explicitly
configured SSH/MCP all use one conformance contract.

## Deferred

AWS topology/services/IaC, distributed workers, remote queues, shared cloud data
services, desktop, marketplace, and autonomous high-risk testing. After Gate 10
and project creation, write a separate AWS RFC.
