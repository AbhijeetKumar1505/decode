# Core Brain and Active Brain

**Status:** bounded Active and deterministic Core implemented in the Python Bridge;
Phase 3 gate complete (2026-10-04). Model-led strategy,
general finding acceptance and the full v2 split remain Target.

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

## Phase 3 Bridge: workflow selection

`CoreIntent` carries a bounded objective, an explicit coding/security/hybrid
mode, and an optional workflow name. It accepts no command, scope, approval,
provider, or permission fields. `CoreWorkflowPlanner.select()` accepts a separate
trusted-caller tuple of `ReviewedWorkflow` pins (name, version, full-definition
SHA-256). Loading a playbook or receiving model output does not create a pin.
Pins record reviewed definitions, not permission to execute their actions; no
review-management UI or signed approval store is implemented by this slice.

The deterministic planner selects an explicitly named reviewed workflow or the
only reviewed workflow with an exactly matching mode. Multiple matches require
input; empty coverage requires input; an unreviewed request, missing/changed
definition, or explicit mode mismatch is blocked. Definitions are copied and
validated, and the review set is bounded to 64 unique names. Decisions carry
schema version 1, a sanitized-intent fingerprint, reviewed workflow identity,
unchanged stage gates, and a fixed public reason. They contain no commands,
execution transport, raw objective, or model reasoning.

`WorkflowRunner.start_core()` rechecks the selected definition before compiling
its existing DAG and persists the selection under `environment.core_selection`.
It creates only pending task/plan state; it neither calls an executor nor grants
scope. Caller-supplied scope remains separate, empty scope stays empty, and the
destructive override remains false. Resume checks the intent, definition,
criteria, and graph material against the saved selection before stage execution.
Human stages and per-action governance still apply. Existing `start()` runs
remain compatible and do not claim Core selection provenance.

This is a programmatic selection baseline, not natural-language strategy,
cost/time accounting, material plan application, finding acceptance, or general stop
arbitration. Schema version 1 is not a runtime FSM version.

## Phase 3 Bridge: bounded Core handoff

`TaskState.revision` starts at zero for legacy JSON and increments through task
mutation helpers and workflow checkpoints. `CoreStageDecision` binds one session,
task revision, full state fingerprint, reviewed workflow fingerprint, node
fingerprint, and the existing stage step bound. The state hash excludes task
creation/update timestamps and the latest decision/consumption bookkeeping; it covers scope,
target, provider metadata, questions, graph state, and typed Active records.
Direct material edits therefore invalidate decisions even without a revision bump.

`decide_core()` saves a deterministic, non-executing decision. Ready stages are
chosen in reviewed declaration order; already-paused human gates take priority.
Possible outcomes are delegate, await approval, needs review, complete, failed,
and budget exhausted,
with fixed public reasons. Unresolved questions, interrupted handoffs, running or
review-paused agent work, and unverified compatibility completions cannot delegate.
Completion means all Bridge stages succeeded with matching gated Active records
for agent work, not proof of general semantic objectives or confirmed findings.

`run_core()` accepts only the latest issued, unchanged, unconsumed decision.
It persists consumption and a dispatch-pending marker before handing one stage
to the shared runner/Active boundary. Successful handoff never starts a second
stage: callers must request a fresh decision. Untyped completion claims, changed
Active envelopes, and results exceeding the declared step bound stop for review.
Errors and cancellation retain typed terminal handoff. A surviving pending
dispatch marker fences both the bounded and compatibility runner paths; it is
never automatically reset or replayed.

Core hands callbacks an isolated task/context copy and fingerprints the whole
working task before handoff. Callback changes to authority, selection, guards,
other nodes or mission state yield material-change review, not durable Core
mutation. The authoritative scope/plan/metadata remain intact, so subsequent
human replacement cannot inherit a callback's invented authority.

`approve_core_stage()` is a separate explicit trusted-human-caller operation for
an awaiting-human decision. It advances only that workflow gate and never starts
agent work or approves a consequential capability. Scope and action approvals
remain independently enforced by the existing coordinator. Decision issuance
and approval are not model tools. Original `start()`/`run()` remain compatibility
APIs; normal runs do not become Core-bounded merely by loading this code.

The latest decision is persisted, not a signed authorization token or full event
history. These guards support the sequential local runtime, not atomic dispatch
across concurrent processes/workers; compare-and-swap/leases belong to Phase 5.
Full resource accounting, model-led strategy and the full Core/Active split remain
Target. The bounded operator controls and reviewed replacement policy below are
implemented without changing the execution coordinator.

## Phase 3 Bridge: mission reservations and budget stops

`start_core(..., budget=CoreMissionBudget(...))` opts a trusted caller into
mission limits: `max_stage_dispatches` (0–1024) and `max_reserved_steps`
(0–32768). Integers are strict; zero denies the corresponding allocation rather
than meaning unlimited. `CoreBudgetState` persists limits and cumulative
reservations under `environment.core_budget`, with schema version 1 and validated
counter relationships. These are stage/step bounds, not tokens, dollars, time,
CPU, or memory accounting; UTOS remains a later phase.

Before each agent-stage handoff, Core requires capacity for one dispatch and the
entire reviewed `stage.max_steps` allowance. If insufficient, a state-bound
`budget_exhausted` decision carries a fixed reason and no delegated node. The
runner blocks before calling Active or a model; it does not shrink criteria,
truncate a stage, choose a cheaper workflow, or grant new authority. Failure,
interruption, questions and unverified work retain their review precedence.
Already-verified workflow completion is not relabeled as budget exhaustion.

Consumption, the pending-dispatch marker, and the full reservation are saved
before execution. Failure, denial, cancellation, or interruption never refunds
that reservation automatically. These counters record conservative allocations,
not actual operations performed. Human workflow-gate approval consumes neither
dispatches nor step reservations and still cannot approve a consequential action.
Limits and usage participate in the decision state hash; material changes require
a fresh decision. An Active callback that tries to modify/refund the budget is
stopped for material review, and the reserved ledger is preserved.

Budgeted missions cannot use compatibility `run()` to evade limits; they require
`run_core()` and the explicit Core human-gate API. Budget omission and older
saved Core JSON remain unbudgeted compatibility behavior; mission budgets are
not inferred from model intent or silently attached on resume. There is no
automatic top-up/refund or signed budget-authorization service. Concurrent
reservation claims still need Phase 5 leases/CAS; UTOS accounting is Phase 7.

## Phase 3 Bridge: review requests and dispositions

Non-delegating review, failure, and budget stops now carry a typed
`CoreReviewRequest` inside the issued `CoreStageDecision`. Its enclosing decision
binds the session, task revision/state hash, and reviewed workflow. When an
incomplete Active result matches that session, node, node material and workflow,
the request records its typed outcome/escalation kind and a hash of the Active
record. `NeedsReplan` or a material-change escalation produces `material_replan`;
other bound incomplete results produce `escalation`. Missing or mismatched proof,
interruption without a bound result, questions and budget stops remain generic
`review`. No cause is inferred from error prose. Public reasons are fixed; raw
model text, failed-criterion prose, credentials and command payloads are not
copied into requests. A node reference is diagnostic, never a delegation.

The decision's `fingerprint()` supplies a deterministic identifier for the full
bound request/decision. `decide_core()` persists the latest request with its
decision; issuance does not execute anything. It is not an authorization token.

`review_core(CoreReviewResolution(...))` is a separate trusted-human-caller API.
Only `acknowledged` or `rejected` dispositions exist, not approval or proceed.
The latest issued decision must still match deterministic recomputation and be
unconsumed. The runner saves consumption and the latest typed resolution under
`environment.core_review_resolution`, marks the mission blocked (or retains
failure), and advances the task revision. Persistence failure is not success.
The saved resolution participates in later state hashes; historical records
remain historical, not fresh authorization. Load validates its structure,
session and workflow provenance. There is no signed human identity or immutable
review event history in this sequential local Bridge.

Both dispositions preserve graph, gates, scope, Active proof and budget usage.
Neither resets an interrupted dispatch, retries a refusal, installs a dependency,
refunds credits, applies a proposed plan, approves a capability or invokes an
executor. Fresh decisions still report the unresolved stop. Compatibility
`run()` cannot bypass a Core review stop even in unbudgeted Core runs; ordinary
non-Core workflows retain compatibility behavior. Human workflow-gate approval
remains a different API and cannot stand in for review of missing Active proof.

Review disposition alone cannot apply a material plan; the separate reviewed
replacement API below does so without reusing action approval. Scope expansion,
resource top-up, authenticated service/UI review and model-led strategy remain
Target. A changed definition still cannot resume its old plan: restore it or
create a separately reviewed replacement. Concurrent consumption is Phase 5.

## Phase 3 Bridge completion: strategy, stop and reviewed replacement

New Core runs persist `CoreStrategy`: the exact reviewed workflow and declaration
order, one bounded stage per fresh decision, and human-reviewed replacement with
no automatic replay. The strategy is deterministic and validated against the
reviewed definition on load; it is not model-generated strategy or authority.
Core strategy supports at most 64 stages. Older Core JSON without this additive
record retains its existing binding checks; no scope or budget is backfilled.

Stop arbitration is fixed: explicit operator stop, failure, interrupted/review
work, missing bound completion, unanswered input, verified completion, human
workflow gate, insufficient mission capacity, or one ready agent stage. Scope,
dependency, approval, safety and verification refusals arrive as typed Active
escalations; Core never retries them automatically. `stop_core()` consumes a
fresh issued decision and persists `CoreMissionStop`. A fresh decision returns
`stopped`, with no executor or permission. Pending handoffs and terminal failure/
completion records are preserved, and compatibility execution cannot resume it.
This is a safe-boundary operator stop, not concurrent process cancellation.

`replan_core(decision, intent, reviewed)` is an explicit trusted-human operation,
separate from acknowledgement and workflow-gate approval. Only an unresolved
review/failure/budget decision can request replacement; ready, stopped, running
or interrupted-dispatch work cannot. Unanswered mission input must first be
resolved by a trusted caller; replanning never clears it. The mission objective/
mode must remain unchanged and the replacement must have a separately reviewed
exact pin. New
gates and instructions are taken unchanged from that reviewed definition.

The runner saves a stopped parent and `CoreReplanTransition` before creating a
new pending session. The child has `CoreReplanOrigin`, identical target and scope,
and the same budget limits and cumulative reservations. Mission constraints and
extra completion conditions are retained, never silently removed. Extra mission
criteria not covered by the Bridge stage-proof contract require review before
Core can declare completion; model prose cannot satisfy them. Final runner
arbitration checks the same Core decision before reporting completion or closing
a session, including unbudgeted Core compatibility runs. The child receives
no prior action approval, successful node state, Active proof or completion credit. The
old graph, observations and evidence remain intact. Parent/child linkage must be
committed before the child can load or delegate; partial persistence leaves it
non-executable and the parent stopped. No rollback resumes the old work.

Load checks the whole ancestor chain, bounded to 32 replacement transitions;
cycles, missing parents, changed selection/authority, missing linkage, raised
caps or refunded usage fail closed. Each ancestor stays stopped, so sequential
replacement cannot fork a live mission or refill budget. There is no atomic
multi-worker replacement transaction: concurrent CAS/leases remain Phase 5.
Replanning performs no execution or dependency installation. It is not authority
to repeat a denied/consequential command; each new action still requires scope,
exact validation and fresh coordinator approval where applicable.

The `decode core` CLI exposes candidate inspection, non-executing selection/start,
status, decision issuance, one-stage advance, human workflow-gate approval,
stopped review disposition, operator stop and reviewed replacement. Pins are
explicit operator inputs, never inferred from discovery or exposed as model
tools. CLI creation requires finite dispatch/step caps and defaults to empty
scope. Mutation commands require the identifier of an already-issued decision;
`issued_core()` validates freshness before executor initialization and operation
methods revalidate before consumption. Stops never initialize a model/host
executor. See [the operator workflow](WORKFLOWS.md#core-operator-controls).

This completes the Phase 3 deterministic local Python Bridge implementation,
not the complete target Brain system. The gate proves reviewed workflow/criteria
selection with public reason, bounded Active execution and preserved authority,
including live local, Kali WSL and Docker conformance with scripted models.
General semantic deliverable validation and finding acceptance belong to later
workflow/evidence depth; resource usage, FSM/concurrency, distributed workers,
service authentication and AWS remain outside this phase.

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
boundary owns local verification and handoff; full Core strategy remains Target.

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
