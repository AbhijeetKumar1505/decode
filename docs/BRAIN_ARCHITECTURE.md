# Core Brain and Active Brain

**Status:** bounded Active runtime implemented in the Python Bridge; Core and
the full v2 split remain Target

## Decision locality

Core interprets authorization/goal, selects workflow/criteria, allocates budget,
creates/materially revises DAG, accepts findings, and stops/pauses. Scheduler
selects ready nodes. Active retrieves context, proposes/invokes authorized
capabilities, retries safe reads, normalizes observations, and escalates.
Verifier/Core gates finding confirmation.

## Core contract

Inputs: objective, authorization, task/workflow/DAG state, verified observations,
evidence, policy, budgets, provider health, questions. Outputs: typed workflow,
criteria, graph, budget, delegation, approval/input/replan, finding, completion,
or failure decisions with public reason and state version.

## Active contract

Receives one authorized node/capability envelope. Owns context, working memory,
governed invocation, observation, bounded recovery, local verification,
memory/evidence update, escalation. Returns Completed, NeedsApproval, NeedsInput,
NeedsReplan, Blocked, or Failed.

```text
Strategic: observe -> interpret -> decide -> delegate -> review
Operational: context -> capability -> execute -> observe -> verify -> update/escalate
```

Core does not wake for every read; Active cannot change mission. Deterministic
scheduler/policy do not require models.

Runtime states: INITIALIZING, UNDERSTANDING, PLANNING, EXECUTING, WAITING,
VERIFYING, RECOVERING, REPLANNING, AWAITING_APPROVAL, COMPLETED, FAILED,
CANCELLED.

Active escalates scope/provider changes, missing approval, repeat side effects,
workflow/criteria changes, insufficient evidence, exhausted budget, untrusted
dependencies, and user input.

Logical model roles are core, worker, reasoning, security, reviewer, summarizer,
fast. UTOS maps roles to compatible providers/models.

Migration: wrap ToolUseLoop behind Active; move state/observation services; add
deterministic workflow baseline; add Core decisions; keep direct agent as
compatibility workflow; shrink UniversalAgent after parity/migration tests.

## Phase 2 Bridge progress

The bounded tool loop now fails closed when declared completion conditions
remain unsatisfied after its replan allowance: it checkpoints a blocked task
and returns `verification_failed` with failed criteria. A model's final message
cannot override that verifier result. The Bridge workflow adapter passes
measurable stage gate criteria into that verifier and returns typed
`Completed`, `NeedsReplan`, `Blocked`, or `Failed` stage outcomes. Unverified
stages pause for manual review; dependents do not run. General stage objectives
and semantic deliverables still require later validators. The bounded Active
boundary owns local verification and handoff; Core strategy remains Target.

A narrow model-free Bridge now accepts a typed `ReadStageAction` bound to the
workflow name/version, stage, and session. It executes only one of six explicit
READ host capabilities through `HostController` and `ExecutionCoordinator`;
`list_tools` uses the selected execution provider, while file/process/service
reads retain the existing local host semantics. Only a timed-out READ may be
retried once; denials, write/command actions, and interrupted stages are never
automatically replayed. The workflow gate still determines whether the
observation suffices. This is a programmatic runner path, not a new CLI mode
or broader model-free capability families.

The Bridge now builds a typed, bounded stage-context snapshot from the durable
plan before either adapter starts. The agent prompt receives at most eight
redacted prior results with field limits, plus bounded instructions and
guidance. Context is observational only, never an authority grant. A READ
timeout is retried only when both status and error category say timeout and
the exact action remains unchanged; ambiguous failures, cancellation, denials,
and telemetry failures stop for review or failure. Retry count cannot exceed
the stage step budget. This is a narrow recovery
classifier, not a general Active recovery engine.

`ActiveStageRuntime` is the shared one-node boundary for both adapters. It owns
the plan-bound context snapshot, working observations, local verification, and
typed completion/escalation. No model-free security/network action family or
cross-node recovery is claimed.

The model-free READ path now emits a typed `ActiveNodeResult` tied to the
durable workflow and node fingerprints. It contains per-attempt request IDs,
provider/status, protected evidence references, and only allowlisted file
signals; raw file content is not copied into this record. The runner checks
the binding and gate outcome again before checkpointing it. An optional exact
file SHA-256 gate requires a successful, evidence-linked `file_read` observation.
This is a narrow, deterministic objective check, not a finding confirmation
mechanism. Model-driven stages project
governed coordinator results into the same typed observation record when an
action occurs. The adapter counts only those captured results, not model step
text or unverified task artifacts. A stage may also require an exact byte
length from the same evidence-linked file-read observation as its digest.
Model finals with no governed action produce a typed verification escalation;
completion requires protected governed evidence. The bounded
context now adds at most eight protected evidence references from completed,
fingerprint-matching dependency nodes; references do not grant authority.
Non-completed Active results include a typed escalation category and optional
governed request ID. Scope/approval, missing dependency, timeout, safety,
verification, budget, and material-change labels support review and handoff;
they do not authorize retry. Legacy incomplete records load with an explicit
unknown category. General objective validation and recovery orchestration
remain follow-on work beyond the Phase 2 baseline.

The Bridge can now check one concrete artifact deliverable: a declared absolute
path plus exact SHA-256 must match the same successful evidence-linked governed
file read, with byte length if declared. Only a path fingerprint is stored in
the Active observation. A pre-existing file can satisfy this presence/content
check; it does not prove creation, semantic correctness, finding confirmation,
or ongoing integrity after the read.

## Phase 2 lifecycle closure

The model adapter stops at its first failed action. Denial, missing approval,
missing dependency, telemetry failure, and consequential failure cannot
trigger another model call or automatic retry. The explicit model-free READ
timeout rule is the only recovery retry. Active budget exhaustion checkpoints
blocked state; ordinary interactive-loop bounded resume behavior is unchanged.

Before another governed call, the stage checks its context/scope/node snapshot
and selected provider identity. A changed envelope produces a non-executing
coordinator refusal with mandatory telemetry and material-change escalation.
The coordinator checks the envelope again after approval and awaited executable
preparation, before launch; approval cannot outlive a material change or the
earlier grant/request expiry. Host command restrictions and provider/session
bindings are synchronously revalidated at launch. Dependency material and typed
Active records are part of the envelope. Existing pre-execution restrictions
are composed with the stage check and restored when the loop ends.
The runner refreshes durable state between nodes and verifies dependency
readiness. Every validly bound terminal path, including no-action errors and
cancellation, records typed handoff with its governed request ID when present;
errors omit raw exception text.
Completed nodes and review-paused nodes are not automatically replayed.
