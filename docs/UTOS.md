# Unified Token Optimization System

**Status:** v2 Target; current usage/routing are foundations

## Purpose

UTOS decides what model, context, and computation are worth spending. It is a
resource governor, not orchestrator or safety authority.

## Accounting

Deterministic required infrastructure: normalized tokens, cost/latency,
reservations/reconciliation, cache/context/model/tool-call records, budgets, hard
limits, and audit.

## Intelligence

Evaluable policy: difficulty, context/retrieval, logical-role routing,
compression/cache, retry/parallelism allowance, expected value, safe fallback.

```text
decision -> data/difficulty -> reserve -> compile context -> select role/model
 -> Model Gateway -> normalize usage -> reconcile -> record outcome
```

Every call records task/workflow/node/role, provider/model/version, available
token categories, cost, latency, fallback, context/compression versions, public
reason, and verification. Unknown fields remain unknown.

Use code for validation/scheduling/accounting/parsing/policy/state; worker roles
for local interpretation; Core/security/reviewer for material judgment.

UTOS cannot cross data/locality/retention policy, omit scope/evidence, increase
authority, retry consequential tools, mark completion, or fabricate precision.

Evaluate fixed baseline, workflow, brains, and UTOS on identical tasks using
verified quality, safety, tokens, cost, latency, calls, context, and intervention.

Implementation: normalize usage; reservations/budgets; context/cache versions;
routing behind UTOS; deterministic context baselines; feature-flag intelligence;
publish comparisons.
