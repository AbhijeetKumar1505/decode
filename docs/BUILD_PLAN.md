# De-code v2 Build Plan

**Status:** Canonical target and sequence
**Last reconciled:** 2026-09-17
**Scope:** Local Linux, WSL 2, and Docker first; AWS Deferred

## Thesis

De-code is a governed engineering and authorized-security execution system.
Models contribute interpretation, hypotheses, planning, and judgment;
application-owned workflows, state, policy, capabilities, evidence, memory,
verification, and resource controls provide operational competence.

```text
User/Interface
 -> Core Brain (strategy, workflow, DAG, budgets, stop)
 -> Workflow Engine (phases, dependencies, gates, checkpoints)
 -> Active Brain (bounded operations, context, recovery)
 -> Execution Kernel (capability, provider, scope, risk, approval)
 -> Verification/Evidence
 -> State/Events/Memory/Usage/Audit
```

## Invariants

1. Model responses are proposals, not authority.
2. Every action crosses one coordinator immediately before execution.
3. Discovery and execution use the same provider.
4. Scope covers targets, network, files/outputs, and credentials.
5. Launch is not success; non-zero exits fail unless explicitly mapped.
6. Findings require evidence and validation.
7. Workflows own procedure; skills/prompts guide.
8. Core owns strategy; Active owns bounded operations.
9. Resume only from safe boundaries.
10. UTOS cannot weaken policy or verification.
11. Local operation is first class.
12. Current, Bridge, Target, Research, Deferred are labeled.

## Baseline

Current Python modular monolith includes CLI/TUI, universal loop, coordinator,
governance, host capabilities, provider classes, task/DAG/verification,
SQLite/memory/evidence/audit, MCP, and model foundations. The current worktree
adds a markdown workflow Bridge and engineering/red/blue/purple/audit playbooks.

It is not v2: brains are combined, provider-scoped filesystem/session contracts
are incomplete, workflows are transitional, and UTOS is incomplete. The Phase 0
system-tool gateway now binds discovery and execution to one selected provider.

## Phase 0 — Execution truth and safety

Fix non-zero success, strict tool schemas, shell-operator rejection in vector
mode, side-effect/output-path risk and scope, provider-bound discovery/execution,
exact discovery results, and governed HTTP/browser/search contracts.

**Gate:** failure cannot render success; writes cannot bypass scope/approval; a
discovered tool executes in the same provider.

**Status — Current (completed 2026-09-18):** non-zero exits are failures; tool
schemas are strict and visible; shell control syntax is rejected; recognized
outputs are WRITE-scoped; network CLI and required MCP targets cross the target
allowlist; filtered discovery observations remain exact; and `local` or an
explicit `wsl/<distribution>` owns both PATH discovery and execution. Browser,
HTTP, and search are semantic capabilities only when an explicit provider
advertises a strict schema—finding a browser executable does not create one.
External-provider output files and stateful sessions fail closed until Phase 1
adds provider filesystem and session contracts.

## Phase 1 — Stable execution kernel

**Status — Next.**

Define EnvironmentProvider, CapabilityRegistry, PolicyEngine,
ExecutionCoordinator, EvidenceStore, and EventStore contracts. A resolved action
contains provider/tool identity, argv/payload, cwd, inputs/outputs, scopes,
side effects, approval digest, timeout, idempotency, and evidence policy.

**Gate:** one local/Kali WSL task executes, persists, evidences, and resumes.

## Phase 2 — Active Brain

Wrap the current loop with runtime, context, observation, working memory,
recovery, and escalation. It executes one node, retries only safe transient work,
verifies local criteria, and escalates material changes.

**Gate:** a stage runs with or without a model and returns typed completion or
escalation plus evidence.

## Phase 3 — Core Brain

Add intent, strategy, workflow/criteria selection, DAG/delegation, budget,
material replan, escalation, and stop conditions. Core cannot execute.

**Gate:** Core selects an approved workflow with a public reason; Active executes
without expanding authority.

## Phase 4 — Workflow engine v2

Retain markdown as Bridge; promote canonical versioned YAML with Pydantic/JSON
Schema. Hierarchy: workflow → phase → task → capability → tool. Initial families:
engineering, security, and shared evidence/validation/reporting.

**Gate:** bugfix, security audit, and purple validation persist transitions,
pause at human gates, and resume safely.

## Phase 5 — DAG scheduler and FSM

Use DAG for work and FSM for runtime truth. Add graph versions, bounded
concurrency, cancellation, idempotency, checkpoints, retry classes, conflicts,
and approval invalidation.

**Gate:** independent reads parallelize; writes conflict-check/serialize; resume
is safe.

## Phase 6 — Evidence, findings, memory

Finding lifecycle: candidate → confirmed/rejected/not-reproducible → mitigated →
regression-verified/failed. Split working/task/project/repository memory; SQLite
canonical; Markdown/JSON/SARIF exports; symbols/dependencies before embeddings.

**Gate:** no confirmed finding without validation evidence; memory has provenance,
freshness, trust, and project isolation.

## Phase 7 — UTOS

Build accounting first (tokens, cost, latency, cache, context/calls,
reservations/reconciliation/budgets), then intelligence (context, role routing,
compression, difficulty/value, retry/parallelism).

**Gate:** every model call is budgeted/attributable; architecture variants are
comparable.

## Phase 8 — Local API and TypeScript CLI

Expose stable runtime contracts via FastAPI/events. Build Commander/Ink/Zod CLI
as client. Keep Python CLI until parity/rollback. Later desktop uses same API.

**Gate:** task start/observe/approve/pause/resume/cancel/inspect parity.

## Phase 9 — Security workflow depth

Implement engagement intake/scope lock, inventory, attack surface, threat model,
coverage, controlled validation, independent review, remediation/regression,
telemetry/detection gaps, and evidence-backed reports. Red/blue/purple cooperate.

**Gate:** controlled labs produce evidenced outcomes with zero scope violations.

## Phase 10 — Evaluation and distribution

Record workflow/version, criteria, resources, calls/retries, evidence/findings,
validation, and intervention. Package Linux/WSL/Docker with isolation, CI,
upgrade, rollback, and conformance.

**Gate:** benchmark baseline/workflow/brains/UTOS and pass environment suite.

## Phase 11 — AWS

Only after Phases 0–10 and user project creation. Map—not rewrite—execution,
identity, events, evidence, storage, workers, and observability.

## Migration and done

Add contracts in `src/decode/`, migrate one vertical slice with compatibility,
prove tests/state/CLI, extract service/shared schemas after boundaries stabilize,
then add TS CLI. Remove compatibility only after two releases/rollback.

Every phase versions contracts/migrations, tests truth/safety/resume, labels
maturity honestly, and updates [CONTINUATION.md](CONTINUATION.md).

The plan learns workflow explicitness from gstack and coverage-led independent
validation from Cloudflare's security-audit skill without copying their runtime.
