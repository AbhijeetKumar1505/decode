# Decode Research Specification

**Status:** Research

This document records hypotheses and evaluation requirements. It does not override the [Product](PRODUCT.md), [System Architecture](SYSTEM_ARCHITECTURE.md), [Security Model](SECURITY_MODEL.md), or [release roadmap](../ROADMAP.md), and it must not be read as a list of implemented features.

## Research objective

Determine whether capability-first planning, evidence-aware memory, model routing, and bounded adaptation improve authorized cybersecurity workflows without weakening scope, approval, privacy, reproducibility, or auditability.

## Verified product baseline

At the 2026-08-07 reconciliation, Decode has a local CLI/inline REPL, typed skills, capability and agent registries, deterministic planning foundations, local/Docker/WSL/SSH/MCP executors, SQLite persistence, model adapters, and a unified P0 execution boundary with bound approvals, mandatory terminal telemetry, and protected immutable evidence references. Typed provider-portable domain transports and broader capability contracts remain product convergence work rather than research results.

Event bus, FastAPI control plane, PostgreSQL shared state, Redis Streams, Qdrant, distributed workers, isolated third-party plugins, Neural Schema adaptation, and fine-tuned Decode models are planned or research systems.

## Research questions

### Capability planning

- Does planning over stable capabilities outperform direct tool-name selection?
- Can typed completion criteria reduce false success and unsafe retries?
- Which signals best predict missing or incompatible tool support?

### Model routing

- Can a policy filter exclude providers before quality/cost ranking?
- Do local models meet structured-output and security-analysis baselines?
- Can fallback avoid duplicated consequential actions and data-policy violations?

### Memory and Neural Schema

- Which exact, graph, and optional semantic retrieval mix improves evidence use?
- Can experience summaries retain provenance without storing secrets or untrusted claims as truth?
- What review, poisoning resistance, deletion, canary, and rollback controls are necessary before adaptation?

### Multi-agent collaboration

- Can delegated agents operate with strict subsets of parent scope, tools, models, time, and budget?
- How should conflicts, ownership, cancellation, evidence sharing, and approval invalidation work?

## Experimental constraints

- Use only explicitly authorized, controlled, synthetic, or non-routable targets.
- Do not expose private chain-of-thought; evaluate concise public decision reasons and observable actions.
- Models, prompts, datasets, plugins, and tool output never grant permission.
- `WRITE` requires human approval. `DESTRUCTIVE` requires an explicit engagement override and human approval.
- Local, WSL, SSH, and MCP execution are not presumed isolated. Experimental isolation must be measured and documented.
- Missing governance, scope, validation, or mandatory audit services stop consequential experiments.

## Data governance

Research data must have documented provenance, license or consent, permitted uses, sensitivity, retention, deletion, and train/evaluation split. Do not use leaked data, real credentials, private penetration-test reports without permission, copyrighted course/exam material without rights, or operational logs containing target secrets. Sanitize and deduplicate before use and keep evaluation sets isolated from training.

## Evaluation dimensions

| Dimension | Examples |
|---|---|
| Task quality | capability selection, parameter validity, plan completion, finding accuracy |
| Safety | scope violation rate, approval bypass rate, secret leakage, unsafe retry rate |
| Reliability | schema validity, parser robustness, timeout/cancellation behavior, reproducibility |
| Evidence | citation/provenance accuracy, raw-output preservation, verification state |
| Operations | latency, cost, memory footprint, provider availability, rollback time |

Every candidate needs a fixed baseline, held-out tests, adversarial cases, confidence intervals where meaningful, regression thresholds, and a rollback path.

## Promotion gate

Research can enter the product roadmap only when it has:

1. Reproducible results against a simpler baseline.
2. No material safety regression.
3. Documented data rights and privacy review.
4. Threat-model and architecture updates.
5. Canary, rollback, deletion, and monitoring plans.
6. Tests that run without live target or paid-model requirements by default.

Delivery order and shipped features are tracked in the root [release roadmap](../ROADMAP.md).
