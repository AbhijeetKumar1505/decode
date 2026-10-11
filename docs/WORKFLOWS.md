# Workflow Architecture

**Status:** Markdown runner is Bridge; versioned YAML DSL is Target

## Principle

De-code must not depend on model memory for methodology.

```text
workflow -> phase -> task -> capability -> tool
```

Skills add guidance, not authority/state/execution/completion.

## Current bridge

`src/decode/workflows/` reads markdown frontmatter, validates dependencies,
compiles stages to `PlanGraph`, persists state, checks gates, pauses for human
stages, and resumes. Agent stages call the governed loop; definitions cannot
embed a bypass. Preserve current workflow/playbook work.

The Phase 3 programmatic `CoreWorkflowPlanner.select()` and
`WorkflowRunner.start_core()` add reviewed-definition selection in front of this
Bridge. A typed objective/mode and separate trusted-caller workflow pins produce
a fixed public reason and the existing stage gates. Selection cannot grant scope
or invoke an executor; compilation persists only pending nodes. Saved Core runs
reject changed selection, criteria, objective, mode, or graph material on load.
`decide_core()` saves a task-revision/state-fingerprint-bound decision;
`run_core()` consumes it and invokes at most one stage through the existing
runner and Active boundary. A fresh decision is required for further work.
`approve_core_stage()` advances a human gate only, without invoking an executor
or granting action permission. Stale, altered, unissued, consumed, or interrupted
handoffs do not replay. The bounded path requires typed Active completion and
checks context and step limits; legacy free-standing results are not upgraded to
verified Core completion. Task revisions are additive JSON state, not a runtime
FSM or a concurrent-worker lease.
`start_core(..., budget=CoreMissionBudget(...))` additionally opts into strict
dispatch/full-stage-step reservation caps. `CoreBudgetState` is saved before
handoff; failed or interrupted allocations are not automatically refunded.
Insufficient capacity produces a non-delegating `budget_exhausted` decision,
without invoking Active or shrinking stage criteria. Human gates are not charged
as dispatches; verified completion and review/failure retain precedence. Budgeted
missions cannot call compatibility `run()` to bypass these limits. Omitted
budgets and older saved Core runs retain unbudgeted compatibility behavior.
These are conservative reservations, not actual token/cost/time measurements.
Review/failure/budget stops carry typed `CoreReviewRequest` records bound by the
issued decision. Matching incomplete Active proof supplies a typed escalation
or material-replan request; missing/mismatched proof stays generic review.
`review_core(CoreReviewResolution(...))` records explicit human acknowledgement
or rejection only. It consumes a fresh issued decision, persists the resolution
and keeps work stopped; no plan change, scope grant, action approval, refund or
retry follows. Core review stops also fence unbudgeted compatibility `run()`.
Ordinary non-Core `start()`/`run()` remain compatibility paths. A separate
human-reviewed replacement API and the bounded `decode core` controls are now
implemented; full resource accounting and model-led strategy remain Target. See
[the Core selection contract](BRAIN_ARCHITECTURE.md#phase-3-bridge-workflow-selection).

For agent stages, declared minimum successful actions and protected evidence
are also bound as deterministic completion criteria *before* the loop accepts
a final answer. A failed criterion yields a typed `NeedsReplan` result after
bounded replan attempts; step-budget exhaustion yields `Blocked`. The runner
checkpoints either for manual review and fences dependent stages. Other
executor errors remain `Failed`. A protected evidence link needs both an id
and hash. The post-stage gate remains a second check. Stages with only the
default final-answer gate still lack objective verification; a model's answer
alone is not proof of the deliverables.

The programmatic `GovernedReadStageExecutor` Bridge takes a typed
`ReadStageAction` for an exact workflow name/version and stage. Its session and
target must match the durable run. It constructs task-scoped target and
filesystem governance and invokes exactly one supported READ host capability
through the existing host controller. A timeout can be retried once when the
action explicitly allows two attempts; all other failures and denials stop.
An executor instance cannot replay its action after an attempt.
The stage gate checks the resulting evidence and action count. A successful
read that does not meet the gate pauses for replan; no model or alternate
execution path is needed. This API is not yet exposed by `decode workflow run`.
It cannot run shell commands, writes, network requests, or human stages.

Both executors compare the supplied session, objective, workflow identity,
target, and full stage metadata against the durable plan before acting. The
agent adapter bounds and redacts prior-result text and workflow guidance
before the model sees it. The model-free adapter checks the exact serialized
READ action before and after each attempt. Only a result whose status *and*
error category are both timeout may consume the one permitted retry, and its
maximum attempts cannot exceed the stage step budget.
Preflight refusals for the model-free action also cross the coordinator as
blocked, non-executing requests so audit, log, and feedback records are kept.

The model-free READ Bridge records a typed Active-node result with workflow and
node fingerprints, per-attempt request IDs, provider/status, protected evidence
references, and allowlisted file metadata signals in sanitized durable task state.
The runner rejects a result bound to another node or a result that disagrees
with the durable gate. A stage may declare `gate.expected_file_sha256` (64
lowercase hex characters); it passes only when an evidence-linked governed
`file_read` reports that exact digest. Model output and untyped evidence links
cannot meet this criterion. Other stage objectives and deliverables still need
deterministic validators. This API remains programmatic, not a CLI workflow
action.

Model-driven stages now receive a coordinator-result callback for each
governed action. The adapter projects only request/provenance metadata and
allowlisted file signals into the same typed Active-node record; model-authored
step text and task-artifact summaries no longer count as governed actions or
evidence. A final model answer after only denied actions pauses for review.
`gate.expected_file_size_bytes` optionally checks the exact non-negative byte
length reported by a successful evidence-linked `file_read`. If size and
SHA-256 are both configured, one observation must satisfy both; two separate
reads cannot be combined to pass. Model-only stages with no governed action
emit a typed verification escalation. All Active completion requires protected
governed evidence even when a workflow uses the default final-answer gate;
general objective proof still requires an appropriate validator.

`BoundStageContext` now includes at most eight protected evidence references
from completed dependency stages whose session, workflow, and node fingerprints
still match. The model may see these references as bounded context, never as
authorization or automatic proof. Each non-completed typed Active result carries
a stable escalation category plus the related governed request ID when there
is one. Preflight refusals with a valid stage binding and action-mutation
refusals retain their coordinator records in that typed result. Older saved
incomplete results with no category load as `legacy_unclassified`; no cause is
invented. Escalation pauses for review or reports failure, but only the existing
explicit READ-timeout rule permits an automatic retry.

For a narrow file-artifact deliverable, a stage can declare
`gate.expected_file_path` together with `gate.expected_file_sha256`; the path
must be absolute and the digest exact. The post-stage gate requires a single
successful, protected-evidence-linked `file_read` whose canonical path
fingerprint and content SHA-256 match. Optional `expected_file_size_bytes`
must match that same read. An unrelated file with identical bytes, two reads
with split signals, model prose, or an unprotected observation cannot pass.
The Active record stores the path fingerprint, not the raw path or content.
This proves presence and bytes when read, not creation by the stage, semantic
quality, or integrity after the read; it does not grant WRITE permission.

`ActiveStageRuntime` is the shared context/working-observation/verification
boundary. All validly bound terminal paths return typed handoff, including
initialization failure, no-action model errors, cancellation, and budget stops.
The runner rebinds model executors to a fresh durable state snapshot between
nodes; completed dependency evidence is carried forward within the context
limits. Unfinished dependencies cannot authorize direct stage execution.

The model stage stops at its first failed action and checkpoints blocked state
on failure or budget exhaustion. Only the explicit model-free READ timeout
rule retries. Scope, node metadata, context, dependency material or typed records, or provider
identity changes stop for material review. Pre-execution material refusals
retain coordinator audit/log/feedback. The coordinator rechecks the envelope
after approval and awaited executable preparation before launch, including the
earlier of grant/request expiry. Host command paths revalidate current scope,
command policy/risk, provider mappings, and external session context without
another awaited preparation step. Scope reset preserves existing restrictions;
the loop composes them with the stage check and restores them when it ends.
In-flight cancellation projects the recorded request into typed Active handoff.
Exception text is never copied into
terminal error messages. Interrupted, completed, and review-paused stages are
not automatically replayed. Invalid result bindings produce a durable typed
material-change escalation rather than accepting their claimed evidence.

The Phase 2 gate is the bounded runtime over this Bridge, not the full workflow
v2 engine. Model-free shell/network/WRITE action families, a model-free CLI
selector, semantic validators, WRITE-origin attestation, cross-node recovery,
and model-led Core strategy remain later work. No runtime dependency or storage backend
was added for Phase 2.

## Core operator controls

The deterministic Phase 3 Core is a Python Bridge over the markdown runner, not
workflow v2 YAML. `decode core` emits JSON. Start is non-executing, requires
explicit finite dispatch/step caps, and leaves read/write/target scope empty
unless the operator supplies it. Workflow discovery is not review: inspect a
definition, then explicitly supply its `NAME@VERSION:SHA256` pin. Selection with
zero/multiple matching reviewed definitions requests input; start refuses it.

Replace placeholders below with inspected definitions and controlled paths:

```text
decode core workflows
decode workflow show <name> --json
decode core select --goal "Inspect a controlled repository" --intent-mode coding --reviewed "<name>@<version>:<sha256>"
decode core start --goal "Inspect a controlled repository" --intent-mode coding --reviewed "<name>@<version>:<sha256>" --max-stage-dispatches 4 --max-reserved-steps 32 --read-root /path/to/controlled/repository
decode core status <session>
decode core decide <session>
decode core advance <session> --decision <decision-id>
```

`decide` saves a fresh non-executing decision and prints its `decision_id` and
typed body. `advance` consumes exactly that issued decision and delegates at most
one stage. Stale, altered, wrong-session or consumed identifiers fail before
executor initialization. Request a fresh decision after each transition; no
command automatically refreshes a decision or loops across stages. Its `provider`
option selects a model provider, not new execution authority. `mode` preserves
the existing plan/ask/auto governance; it cannot override scope or destructive
approval. Returned report status, not successful JSON rendering, states mission
completion or failure.

Other transitions are explicit and require a current issued decision:

```text
decode core approve <session> --decision <decision-id>
decode core review <session> --decision <decision-id> --disposition acknowledged
decode core stop <session> --decision <decision-id>
decode core replan <session> --decision <decision-id> --workflow <replacement-name> --reviewed "<replacement-name>@<version>:<sha256>"
```

`approve` advances only an awaiting-human workflow gate, not a capability.
`review` accepts `acknowledged` or `rejected`; both preserve the unresolved stop.
`stop` prevents further delegation/compatibility execution at a safe boundary;
it does not cancel another process in flight. `replan` is a different human
operation for unresolved review/failure/budget stops, never ready, running,
interrupted or explicitly stopped work; unanswered input must be resolved first.
It selects a separately reviewed
replacement with the same objective/mode, stops the parent and creates only a
new pending run. Target/scope and all used budget are inherited exactly; action
approvals and completion credits are not. Mission constraints and extra
completion conditions are retained. Unsupported extra mission criteria pause
completion for review; stage proof does not prove them. Core callbacks operate on
isolated state and cannot rewrite durable authority, guards or other nodes.
No replanning command runs or installs a tool.
Use the returned new session and request a fresh decision before doing work.
Missing/cyclic/tampered ancestry or an incompletely saved link blocks the child;
the chain is bounded to 32 replacements. An exhausted mission stays exhausted.

These APIs are trusted local operator controls, not model tools or an
authenticated multi-user service. They do not change the inline REPL, and the
older `decode workflow` commands remain compatibility interfaces. Budgeted,
review-stopped or operator-stopped Core sessions cannot use those commands as a
bypass. See [Core lifecycle contracts](BRAIN_ARCHITECTURE.md#phase-3-bridge-completion-strategy-stop-and-reviewed-replacement).
Core CLI OS and SQLite persistence failures return a fixed JSON rejection and
non-zero exit without echoing exception payloads or automatically retrying.

## Target definition

Versioned YAML validated by Pydantic/JSON Schema declares identity/version,
authorization/scope, phases/dependencies/actors/budgets/risk, capability
envelopes, artifacts/evidence, retry/idempotency/timeout, gates, human points,
failure/compensation, and resume behavior. Tools resolve later in the provider.

Engineering families include feature, bugfix, refactor, migration, debug,
performance, review, QA, release, docs, and security fix. Security includes
intake/scope lock, audit, threat model, red, blue, purple, hardening, detection,
incident response, remediation, and regression.

## Finding discipline and runtime

Separate inventory, attack surface, coverage, candidates, controlled validation,
independent review, remediation, regression, reporting. Candidates are never
silently confirmed.

Runner flow: validate definition; create DAG/state; schedule ready nodes; execute
through kernel; record evidence/events; check gates; pause; resume safely;
escalate material changes; complete only declared criteria.

Only independent conflict-free reads run concurrently. Automatic retry is for
explicit transient idempotent work. Consequential retry requires review.

Initial v2 promotion set: `bugfix`, `security_audit`,
`purple_validation`. gstack informs explicit engineering stages; Cloudflare's
audit skill informs coverage, validation, machine-readable findings, and review.
