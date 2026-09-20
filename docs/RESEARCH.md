# De-code Research Specification

**Status:** Research; promotion requires quality and safety evidence

## Hypotheses

Deterministic workflows/runtime can reduce model dependence; Core/Active
separation can reduce resource use without reducing quality; coverage/evidence
security flows can improve precision; provider-bound execution can improve
portability and safety.

## Variants

Fixed-model baseline, current universal loop, workflow, workflow+Active,
workflow+Core/Active, and workflow+brains+UTOS on identical tasks/environments.

## Measures

Verified completion, safe resume, finding precision/recall, false success,
unsupported claims, policy/scope near misses, tokens/cost/latency/context/calls/
retries, conformance, human burden, and reproducibility.

## Controls and data

Pin versions and context manifests; separate deterministic verification from
model judging; use blind review when possible; include negative/injection cases;
report abstention/failure; preserve evidence. Use synthetic repositories, legal
labs, defensive data, seeded bugs, and fixtures—never private engagement data
without rights/isolation.

## Promotion

Require held-out results, safety regressions, resource impact, data-rights
analysis, rollback/migration, and an accepted ADR. Accounting is infrastructure;
optimization is experimental and compared with simple baselines. Research cannot
broaden production authority or auto-replay consequential actions.
