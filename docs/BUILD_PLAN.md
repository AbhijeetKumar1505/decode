# De-code v2 Build Plan

**Status:** Canonical target and sequence
**Last reconciled:** 2026-10-03
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

The full v2 split is not implemented: Core strategy, workflow v2, the runtime
FSM, and UTOS remain Target. Phase 1 established provider-bound kernel contracts;
Phase 2 adds the bounded Active stage runtime over the transitional workflow
Bridge. Provider session/mapping limitations are explicit and fail closed.

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
External-provider output files fail closed unless an explicit writable provider
mapping covers them. Provider-bound sessions require an explicit stateful-session
capability and mapped cwd; WSL and SSH support context-persistent sessions while
Docker and MCP continue to fail closed.

## Phase 1 — Stable execution kernel

**Status — Gate complete (2026-09-24; Bridge contracts remain).** Typed provider identity,
capability, filesystem-mode, host-to-provider path mapping, and execution-context
contracts are now in place. Local paths are explicitly shared; WSL, Docker, and
SSH mappings fail closed until configured; MCP declares no host filesystem.
Configured providers bind cwd/environment and declared outputs to their native
transport. The host controller scope-checks host output paths, maps and rewrites
only classified output arguments, and binds both path sets into the governed
action. Provider sessions now carry immutable session/provider identity and
persist mapped cwd/environment across independently governed actions. Local,
WSL, and SSH declare support; Docker and MCP do not. Resolved-action identity,
side-effect/output metadata, approval binding, and privacy-safe telemetry now
cover governed host CLI actions and provider session commands. Tool discovery
fingerprints executable content inside the selected provider; governed CLI and
external-provider session actions bind absolute executable paths and SHA-256
digests to approval and recheck them immediately before launch. Semantic tool
versions remain unknown; arbitrary CLI inputs and side effects are not yet
fully migrated or inferable. Local compatibility sessions now bind executable
identity, cwd, environment hash, and outputs to approval. Broader all-provider
conformance remains. Offline Docker process-outcome coverage and an opt-in live
Kali WSL smoke check are in place. A locally built Docker test image now passes
live process-outcome checks. Governed task persistence, evidence, and resume
conformance passed on local Linux, Windows-to-Kali WSL, and Docker with a
GNU-compatible cached image. The bounded agent now checkpoints before each
action, after each observation, and on completion; matching unfinished tasks
resume from sanitized persisted state without automatic command replay.
Unresolved actions require manual review. Minimal/BusyBox images do not yet
satisfy the provider discovery helper contract, so all-distro portability is
not claimed. Semantic version and arbitrary CLI input/side-effect inference
remain future hardening, not Phase 1 gate evidence.

Define EnvironmentProvider, CapabilityRegistry, PolicyEngine,
ExecutionCoordinator, EvidenceStore, and EventStore contracts. A resolved action
contains provider/tool identity, argv/payload, cwd, inputs/outputs, scopes,
side effects, approval digest, timeout, idempotency, and evidence policy.

**Gate:** one local/Kali WSL task executes, persists, evidences, and resumes.

## Phase 2 — Active Brain

**Status — gate complete (2026-10-02); bounded Python Bridge.**
Pre-landing gaps are fixed with regressions; final Windows/live Kali WSL/Docker,
native Kali, package build, and independent re-review passed. PR #21 was merged;
[CI](https://github.com/AbhijeetKumar1505/decode/actions/runs/37046975348)
passed lint, Python 3.11/3.12 tests, security, and build
for commit `58c8e0b`. The documentation follow-up requires separate PR checks;
this is not a release. See the
[shipping fixes](CONTINUATION.md#phase-2-shipping-fixes--2026-10-02).
The bounded Active runtime is implemented over the existing Python workflow
Bridge. `ActiveStageRuntime` owns one plan-bound context, bounded working
observations, deterministic local verification, and typed handoff. The model
and model-free adapters share this boundary and the existing coordinator.
Every validly bound stage stop produces an `ActiveNodeResult`, including
initialization/runtime failure, cancellation, budget exhaustion, and a model
final answer with no action. Completion requires a successful protected
governed observation and the declared gate. Unsupported completion pauses
for review. The runner refreshes durable state between nodes, carries bounded
dependency evidence forward, and prevents automatic replay of completed,
interrupted, or review-paused stages.

The model adapter stops at its first failed action; only the explicit unchanged
model-free READ timeout may retry once. Active budget exhaustion checkpoints
blocked state. Context/scope/node/dependency and provider identity changes
require review. A coordinator check after approval revalidates the stage envelope
after awaited executable preparation, immediately before launch; prior checks
remain enforced, including current host restrictions and effective grant expiry.
Dependency material fingerprints and typed records are bound; cancellation
retains the governed request ID. Raw exception details
are omitted from terminal errors.

The following describes the implemented Bridge contracts. Exhausted
verification blocks completion and returns failed criteria. The workflow stage adapter binds
declared successful-action and protected-evidence minima into the loop's
deterministic verifier, and maps its stop reason to a typed stage outcome.
A programmatic model-free Bridge now runs one explicit READ host capability
through the same coordinator, bound to one workflow stage, with at most one
timeout retry. Both stage adapters now bind their context to the durable plan;
agent prior results and guidance have redacted size limits. A retry requires
the exact READ action to remain unchanged and both the result status and error
category to identify a timeout. Broader capability coverage, retrieval adapters,
and cross-node recovery remain follow-on work beyond the Phase 2 baseline.

A Bridge slice records a typed `ActiveNodeResult` for model-free READ
stages: durable workflow/node fingerprints, governed request IDs, provider,
status, protected evidence references, attempt count, and a small allowlist of
verified signals. A stage can require an exact SHA-256 observed from a governed
`file_read`; model text or a free-standing evidence link cannot satisfy that
criterion. This proves only observed file metadata, not general objective or
deliverable completion. The model-driven adapter now captures governed
coordinator results into the same typed observation contract. An optional
exact byte-length check can accompany the digest, and both must belong to
one evidence-linked `file_read`. Model-only stages without a governed action
return a typed verification escalation. General objective validators remain
follow-on work; no model final alone proves deliverable completion.

The Bridge now carries up to eight protected evidence references from completed,
fingerprint-matching dependency nodes into a bounded stage context. These
references are observations, never permission or proof of a new objective.
Non-completed Active results carry a typed escalation category and, where
available, the governed request ID; older saved results without a category
load as explicitly `legacy_unclassified`. Material action changes, approval,
dependency, timeout, safety, verification, and budget cases are classified,
but classification does not retry or grant authority. Only the existing
explicit, unchanged READ timeout may retry once. Cross-node recovery and
general semantic deliverable validation remain follow-on work.

One narrow Bridge deliverable criterion now binds an absolute expected file
path and SHA-256 to the same successful, protected-evidence-linked governed
`file_read`; optional byte length must match that observation too. The typed
record stores only a canonical path fingerprint, never the raw path or file
contents. An identical file at another path cannot pass. This verifies a file
observed at a declared path at read time, not that this stage created it or
that its contents meet a semantic requirement. No WRITE approval is inferred.
WRITE-origin attestation belongs to later evidence/workflow depth. Model-free
execution remains a programmatic API for six READ host capabilities; a CLI
selector and other action families are not required by this gate. Core, full
workflow v2, the runtime FSM, and AWS retain their later-phase status.

The runtime wraps the current loop with context, observation, working memory,
recovery, and escalation. It executes one node, retries only safe transient work,
verifies local criteria, and escalates material changes.

The first slice closes false completion: exhausted verification/replan attempts
must return a non-successful, checkpointed outcome with failed criteria, never
mark the task complete. Knowledge retrieval is a bounded, untrusted input to
Active, not a new execution path or authority source.

**Gate:** a stage runs with or without a model and returns typed completion or
escalation plus evidence.

**Validation:** full Windows `wenv` suite with live Kali WSL and cached,
network-isolated Docker passed (563 passed, 10 skipped, 70 subtests).
Direct Kali full suite passed (565 passed, 8 skipped, 60 subtests). Ruff lint,
formatting, relative documentation links, and diff checks passed. Transient
host startup failures and the user-authorized recovery are preserved in
[the continuation ledger](CONTINUATION.md#phase-2-shipping-fixes--2026-10-02).

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
Build the Engineering Knowledge Layer on project-scoped SQLite graph records,
with provenance, typed edges, lifecycle, and bounded retrieval. Optional
Obsidian-compatible Markdown notes begin as read-only imports. FTS5, embeddings,
and dedicated graph engines are evaluated against the SQLite baseline; no
personal-vault sync or automatic promotion of model claims to verified facts.

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
