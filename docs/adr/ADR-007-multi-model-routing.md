# ADR-007: Route Across Multiple Models by Policy

**Status:** Proposed

## Context

No model is best for every security task, data class, latency target, and deployment.

## Decision

Route by required capabilities, data policy, quality, health, latency, and cost. Record the selected model and rule. Preserve explicit model pinning for reproducibility.

## Consequences

- Quality and resilience may improve.
- Evaluation, provider drift, fallback safety, and cost accounting become mandatory.
- A model change cannot weaken data handling or re-execute external actions.
