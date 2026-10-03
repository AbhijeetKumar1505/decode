# De-code v2 Continuation Ledger

**Updated:** 2026-10-03
**Plan:** [BUILD_PLAN.md](BUILD_PLAN.md)

## Resume protocol

1. Read `AGENTS.md`, docs index, build plan, and this file.
2. Inspect `git status --short`; never reset unfinished work.
3. Inspect source/tests rather than old completion claims.
4. Run relevant tests in Kali WSL from `/mnt/e/hackagent`.
5. Continue the first incomplete phase with satisfied prerequisites.
6. Record exact tests, risks, and next action before pausing.

## Current state

Python modular monolith remains source truth. Target monorepo is not implemented.
Foundations include coordinator, governance, scope, host capabilities,
evidence/audit, SQLite, model adapters/routing, task/DAG/verification, MCP, and
bounded tool loop.

Phase 2's bounded Active runtime gate was recorded complete on 2026-10-01,
then reopened by pre-landing review. The user authorized fixing the gaps,
adding regressions, committing, and opening a PR from `feat/working` to `main`
on 2026-10-02. The fixes below passed final environment validation and independent
re-review. Phase 2's bounded Python Bridge gate is closed and landed through
[PR #21](https://github.com/AbhijeetKumar1505/decode/pull/21), from `feat/working`
to `main`. GitHub records an external merge at 2026-10-02 18:53:12 UTC into
`2aff5bd`; this agent did not merge the PR. The documentation-only follow-up
remains on `feat/working` for separate review. Phase 3 remains Target;
AWS remains Deferred.

Current worktree also has `src/decode/workflows/`, workflow playbooks, CLI
integration, and `tests/test_workflows.py`. Preserve these as Phase 4 Bridge.

## Documentation sync — 2026-10-03

This entry supersedes the historical pending-CI and failed documentation-audit
handoff below; it does not erase prior failures or extend implementation scope.

- Request: sync existing root and subsystem documentation; the user approved
  committing and pushing the sync to `feat/working` for PR #21. The user also
  approved correcting SECURITY.md's stale Phase 0 status without changing its
  authorization rules or remaining isolation/storage/cloud limitations.
- CI verified for `58c8e0b`: [CI run](https://github.com/AbhijeetKumar1505/decode/actions/runs/37046975348)
  passed lint, Python 3.11/3.12 tests, security, and build. This evidence applies
  to that commit only, not the documentation follow-up. PR #21 was initially
  open during this audit and was externally merged before the documentation
  push. No agent-performed merge or release is authorized.
- Documentation corrections cover phase maturity, reviewed-tree validation
  counts, mapped provider/session limits, final launch checks, expiry and
  cancellation provenance, contributor test dependencies, model/runtime-path
  defaults, and the Windows activation example. Obsolete example pages are
  explicitly historical; removed commands and fictional findings are not
  current interfaces or verified advisories. No runtime code or version changed.
- Validation of the documentation worktree: Ruff lint passed; formatting passed
  for 247 Python files. Full offline Windows passed (557 passed, 16 skipped,
  60 subtests, 59.25 seconds); full native Kali passed (565 passed, 8 skipped,
  60 subtests, 57.81 seconds). Relative file links passed across 63 tracked
  Markdown files; patch whitespace passed. The publication credential scan
  found no credentials; numeric CI identifiers were false-positive phone
  matches and now remain only in the verified CI link. These runs do not replace
  the prior recorded live WSL/Docker Phase 2 gates or claim all-distro compatibility.
- Coverage audit: the bounded Active/model-free READ API and exact-file gates
  have reference and explanation coverage, but lack an end-to-end onboarding
  tutorial. Historical security examples are not current how-to coverage.
  No new documentation pages or diagram rewrites are authorized in this sync.
- Independent in-host documentation review completed with no actionable findings
  in the factual phase/provider/configuration/launch-contract corrections. The
  parent separately audited examples and links. Outside-model review remains
  unavailable because source disclosure is not authorized; no source was sent
  externally. The earlier failed audit remains historical, not silently passed.
- After synchronizing the landed base, full Windows passed again (557 passed,
  16 skipped, 60 subtests, 31.19 seconds), as did native Kali (565 passed,
  8 skipped, 60 subtests, 62.33 seconds). Windows CLI help passed. The combined
  Kali test/build command had a quoting failure after pytest passed; a direct
  argument-vector retry built the source archive and wheel successfully through
  the installed Poetry backend. No dependency was installed. A fresh local
  adversarial documentation review found no actionable issues; the coverage
  audit confirmed no new application code paths and 35 unchanged test files.
- Publication: documentation sync committed and pushed as `9c73efa` to
  `feat/working`. GitHub then showed PR #21 already merged with head `58c8e0b`;
  the documentation commit is not in that merge. The user explicitly approved
  a new documentation-only PR from `feat/working` to `main`. The landed base was
  merged locally without conflicts or runtime changes; a follow-up correction
  records the external merge. Next action: publish that PR and verify its new
  CI; prior green checks do not attest to these documentation commits.
  Phase 3 Core Brain remains Target and is not started; AWS is Deferred.
  Do not merge, force-push, implement Phase 3, or deploy AWS in this request.

## Phase 2 shipping fixes — 2026-10-02

- Scope reset preserves the existing deny-only guard, mode, hooks, and approval
  callback while rebuilding task authority and telemetry bindings.
- Awaited executable preparation now precedes the coordinator's final action,
  stage-envelope and policy checks. Effective grant/request expiry is checked
  before every operation, including callers without preparation. Host commands
  then synchronously revalidate filesystem restrictions, command policy/risk,
  provider identity/mappings, and external session context before launch.
- Completed dependency bindings include material node fingerprints and typed
  Active records, not only status.
- Coordinator cancellation retains its recorded result and provider in a
  `CancelledError` subtype; both Active adapters retain cancelled request IDs
  in observations and typed handoff without retry.
- Independent re-review confirmed the original four fixes and found two related
  gaps: actual external host-policy revocation and a shorter grant expiry.
  Both are now fixed with direct fake-provider/fake-clock regressions. A further
  re-review caught the missing expiry check for callers without preparation;
  the same regression now covers both paths. Final independent review closed
  with no remaining blocker attributable to these fixes (24 focused tests and
  7 subtests passed in Kali).
- Corrected targeted tests passed: 133 passed, 2 skipped, 24 subtests. The first
  full run this turn had 3 failures, 559 passes, 10 skips, and 58 subtests:
  Docker was stopped at startup, one test assumed the wrong default provider,
  and another used unsupported session-exec parameters. Docker was started
  without deleting data; fixtures were corrected, not skipped. The subsequent
  full run passed (561 passed, 10 skipped, 59 subtests, 149.01 seconds), before
  the two additional review fixes; final-tree suites must run again.
- Final reviewed-tree validation: Windows with live Kali WSL and Docker
  conformance passed (563 passed, 10 skipped, 70 subtests, 219.12 seconds).
  Native Kali passed (565 passed, 8 skipped, 60 subtests, 47.21 seconds).
  Ruff lint and formatting passed (247 Python files); `git diff --check` and
  relative links across 54 Markdown files passed. Source archive and wheel
  built through the installed Poetry backend without dependency installation;
  Windows CLI help exited successfully. The `build` frontend is an incomplete
  namespace on Kali, so `python -m build` was unavailable; backend builds
  succeeded. The final diff secret scan found only two synthetic TEST-NET
  addresses in tests, not credentials. The native suite has a local evidence
  log record, but the wrapper could not bind a Git content fingerprint; its
  advisory freshness check reports stale. The Windows wrapper could not record
  due to missing runtime-home configuration. Actual test exits/output above
  were retained; no mechanical freshness claim is made. After documentation
  closure, offline Windows passed (557 passed, 16 skipped, 60 subtests,
  24.73 seconds), with lint/format, links, and patch hygiene passing again.
- Optional outside-model review was blocked before execution because it would
  disclose source to an external provider. No source was sent; independent
  in-host review is used instead. Bandit is not installed; no installation is
  authorized. Bandit and CI's clean Python 3.11/3.12/install-build lanes remain
  PR CI checks; no green CI claim is made before their results.
- Publication: implementation/regressions committed as `66ff4c2`, contracts and
  validation as `7526fe8`; both pushed to `feat/working`. PR #21 is open against
  `main`. Initial CI lint, Python 3.11/3.12, security, and build jobs were in
  progress when checked; no green CI claim is made.
- Post-push documentation sync was dispatched but could not start its shell or
  alternate runtime (`helper_unknown_error`). It could not read its skill,
  inspect the repository, or audit documentation health; no edits, commits,
  or pushes occurred. Parent documentation/link validation remains recorded
  above; independent documentation-health audit is unavailable, not passed.
- Next action: review PR #21's CI results before starting the Phase 3 plan;
  optionally rerun the independent documentation audit once its runtime works.
  No input is required for the completed publication request. Do not merge,
  force-push, implement Phase 3, or deploy AWS as part of this request.
  Version remains 1.0.0; this is not a release.

## Phase 2 shipping review — historical blocker (2026-10-01)

This entry records the prior stop; the approved fixes above supersede its
pending-approval state. Historical validation failures remain recorded.

- Request: the user authorized committing the Phase 2 changes on `feat/working`
  and creating a PR targeting `main`, not merging or implementing Phase 3.
- Git: `HEAD` and fetched `origin/main` are `c8d01e5`; no open PR exists for
  `feat/working`. All Phase 2 work remains uncommitted. No staging, commit,
  push, branch creation, or PR creation has occurred in this shipping attempt.
- Review: the shipping skill's checklist, independent coverage/plan audit,
  and independent adversarial pass found four gaps:
  1. `GovernedAgentStageExecutor` resets scope using `UniversalAgent.set_scope`,
     which replaces the coordinator and loses an existing deny-only execution
     guard. An offline probe confirmed the guard is absent after this reset.
  2. The coordinator's stage-envelope check precedes the host controller's
     awaited executable recheck. A material scope change during that preparation
     can reach launch before the runtime reports `material_change` afterward.
     The adversarial reviewer reproduced this with fake providers.
  3. `ActiveStageRuntime._envelope` binds dependency status but not dependency
     material fingerprints; changing completed dependency parameters after
     binding does not invalidate the context. The coverage reviewer reproduced
     this in memory.
  4. In-flight coordinator cancellation emits terminal telemetry and re-raises
     before the Active adapter projects the cancelled result. Typed handoff can
     lose the cancelled request ID, though telemetry and replay fencing survive.
- Files requiring review/fixes: `src/decode/universal_agent.py`,
  `src/decode/workflows/agent_executor.py`,
  `src/decode/runtime/{coordinator,host_controller}.py`, and neighboring
  workflow/agent-loop/governance tests. No implementation fix is applied yet.
- Fresh validation: Ruff lint and formatting passed (247 Python files).
  The first all-live Windows run failed because Docker Desktop was stopped
  (4 failed, 555 passed, 10 skipped, 50 subtests). The installed engine was
  started without restarting WSL or deleting containers/images. Docker then
  reported 29.8.0 and both cached images were present. The unchanged full
  Windows/live-WSL/Docker rerun passed (557 passed, 10 skipped, 55 subtests,
  111.73 seconds); direct Kali passed (559 passed, 8 skipped, 45 subtests,
  45.10 seconds). After recording the blocker, the offline Windows suite passed
  (551 passed, 16 skipped, 45 subtests, 24.14 seconds), lint/format passed again,
  and relative links across 54 Markdown files plus `git diff --check` passed.
  Passing tests do not negate the uncovered review defects.
- Tooling limits: Windows has neither `build` nor `bandit`; Kali has `build`
  but not `bandit`. No dependency was installed. Package build and Bandit have
  not run in this shipping attempt. No outside-model review or post-push
  documentation-sync pass ran because shipping stopped before publication.
- Next action: obtain approval to fix the four review findings and add targeted
  regressions, rerun lint/format/full environment suites, then finish the
  pre-landing review, secret scan, build check, explicit-path commits, push,
  documentation sync, and PR creation against `main`. Preserve all existing
  Phase 2 edits and historical failure records. Never force-push or merge main.
- Required input: approval for the security-sensitive fixes before publishing.
  The earlier guard-fix question covers the first finding; the remaining
  findings also require direction. AWS remains Deferred.

## Phase 0 completion

The seven confirmed defects are closed:

1. Non-zero host commands produce ERROR, never success.
2. Shell operators, substitutions, redirections, and interpreter command strings
   are rejected in argument-vector mode.
3. Host, coding, playbook, and MCP schemas are shown to the model and strict
   validation rejects unknown, missing, wrong-type, and malformed parameters.
4. Local or qualified WSL PATH discovery and execution share provider identity;
   configured provider selection is no longer metadata only.
5. Recognized output flags raise WRITE risk, resolve output paths, bind approval,
   and cross write scope. External-provider outputs require an explicit writable
   mapping.
6. Filtered discovery observations receive an exact 64k budget and explicit
   truncation metadata outside that path.
7. Installed browsers remain CLI binaries. Semantic HTTP/browser/search tools
   must be explicitly advertised by a provider with strict schemas; required
   targets cross the engagement allowlist.

Recognizable network CLI targets also cross `ScopePolicy`; out-of-scope commands
are denied before provider execution.

## Documentation completed

Canonical plan, migration map, brain/UTOS contracts, workflow-first engineering
and security, all subsystem docs, ADRs, and all eight root Markdown files are
aligned. The root README, roadmap, contributor/agent guidance, security policy,
feedback policy, changelog, and conduct policy now point to the v2 plan and use
the same maturity vocabulary. AWS is Deferred.

## Phase 1 gate complete — provider contract, mapped context, sessions, and actions

Phase 1's local Linux/Kali WSL/Docker task gate is met. PR #20 was merged into
`main` on 2026-09-27; `feat/working` was fast-forwarded to the merge commit
before Phase 2 work:

- `EnvironmentProvider` is now the typed base contract; `ExecutionProvider`
  remains the compatible governed execution subclass.
- Immutable identity declares provider name/kind/qualifier, platform,
  filesystem mode, capabilities, and configured path mappings.
- Filesystem modes distinguish local shared paths, mapped WSL/Docker paths,
  remote SSH paths, and MCP with no host filesystem.
- Path mapping resolves host paths lexically, selects the most-specific root,
  and fails closed for unmapped paths or writes through read-only mappings.
- `ExecutionContext` validates absolute provider cwd/output paths and a strict
  environment map; unsupported context fields fail with a stable error.
- Local execution applies cwd/environment directly. WSL uses `--cd` and
  `/usr/bin/env`; Docker uses working directory, environment, and configured
  mounts; SSH constructs a quoted remote cwd/environment command; MCP rejects
  filesystem context.
- External output commands are host-scope checked, mapped through the selected
  provider, rewritten only at classified output argv positions, and included in
  the approval-bound request. Unmapped and read-only outputs still fail closed.
- Contract, rewrite, provider-context, and host-controller regression coverage
  lives in `tests/test_execution.py`, `tests/test_hostcontrol.py`, and
  `tests/test_host_integration.py`.
- ProviderSession binds an immutable session ID and exact provider identity to
  mutable validated execution context, bounded command count, transcript, and
  closed state.
- Local, WSL, and SSH declare stateful-session support. Docker remains disabled
  because commands use fresh containers; MCP remains disabled because it has no
  host filesystem/session contract.
- Provider session open maps and binds the authorized host cwd. Every exec
  rechecks command policy, network restrictions, current filesystem scope,
  provider identity/mapping, output scope, and output mapping before entering
  the governance gate.
- Session approval material contains session/provider identity, host/provider
  cwd, state transitions, exact provider argv, and host/provider outputs. cd
  verifies the mapped provider directory before committing state.
- Unsupported providers and unmapped cwd/output paths fail closed without local
  fallback.
- Governed CLI and provider session commands now carry a strict, typed
  ResolvedAction with exact argv, target, provider/tool identity, cwd,
  host/provider output paths, known side effects, timeout, idempotency, and
  protected raw evidence/raw-only parser policy.
- The capability schema versions populate ExecutionIdentity. Tool version is
  deliberately empty until verified in the selected provider; arbitrary CLI
  input paths and side effects cannot yet be inferred.
- The action is bound into the approval digest. The coordinator checks its
  coherence with the execution request and rechecks the digest immediately
  before execution. Approval receives redacted action details; audit, logs, and
  feedback receive a summary without argv or path values.
- Unknown CLI effects and session cwd changes require at least WRITE risk.
  Output and cwd paths must be absolute and NUL-free.
- Local compatibility sessions now resolve against their captured PATH and bind
  executable path/SHA-256, cwd, environment hash, and declared outputs to
  approval. A built-in `cd` binds its destination as a session-state change.
  Changed identity or context blocks launch; missing tools are never installed.
- Docker now distinguishes wait timeouts from API failures and malformed wait
  results, preserves available stdout/stderr, and removes created containers
  even when start fails. Explicit create/start prevents SDK auto-pull on a
  missing image. Offline tests cover these outcomes and missing SDK; opt-in live
  Kali WSL and Docker process-outcome checks passed.

## Phase 1 closure and next slice

Provider mapping configuration is now exposed at the project/user environment
boundary through `DECODE_PROVIDER_MAPPINGS`, consumed by the universal agent and
interactive host controller. Exact provider identity selects a mapping;
duplicates, malformed entries, and mappings on providers without a filesystem
contract fail closed. Read-only is the default. Mapping remains separate from
filesystem scope and approval. Factory tests cover identity and validation.

An exact `list_tools` lookup returns a SHA-256 fingerprint for a matching
executable in the selected provider. Provider discovery queries only `PATH`
instead of capturing the full environment, and rejects invalid PATH entries.
Missing tools return an empty match without installation. `shell_command` and
all session actions now resolve every executable stage to an absolute provider
path, bind each path and digest to approval, and recheck each
digest immediately before launch. This includes `sudo` and its wrapped command.
Target, command, and filesystem scope checks precede provider inspection. No
semantic version is inferred from a digest or an untrusted `--version` probe.

The governed loop now writes a sanitized operational-store checkpoint (SQLite
by default) before each action,
after each observation, and on completion. Same-session, same-objective resume
requires balanced action/observation records and refreshes live scope and
provider environment; an unresolved action needs manual review, not replay.
Checkpoint failure stops later tool calls. Tests verify protected evidence
hashes, logs, audit, and feedback for local Linux, `wsl/kali-linux`, and Docker.
Broad provider PATH scans recover from stale nonexistent directories in WSL.
The earlier BusyBox test image remains valid for process outcomes only; a
cached GNU-compatible `debian:bookworm-slim` image was used for governed tool
discovery without adding a repository file. Minimal images remain unsupported
for this path; no all-distro claim is made.

Phase 2 Active Brain has started with verifier-truth hardening. Next, bind one
authorized operation to typed local completion/escalation, deterministic
recovery, and evidence. A separate
hardening slice may address semantic tool-version attestation, arbitrary CLI
input/side-effect declarations, and stronger Docker image identity binding.

Keep Docker/MCP sessions and any provider without an explicit session capability
fail-closed. Keep cwd/output actions fail-closed when no explicit mapping covers
them. Live Docker process-outcome and governed task lifecycle conformance
passed. Do not infer semantic browser/search from an installed executable. A
content fingerprint does not attest to an
external interpreter or shared libraries.

## Phase 2 closure — bounded Active runtime

- Objective: complete the Phase 2 gate, not the full later-phase v2 split.
- Implementation: shared `ActiveStageRuntime` owns plan-bound context, working
  observations, local verification, and typed handoff for both adapters.
  Completion requires successful protected governed evidence and the declared
  gate. No-action finals escalate verification; runtime errors, cancellation,
  budgets, and invalid result bindings cannot silently complete.
- Safety: the model stops at its first failed action. Only an explicitly
  configured unchanged model-free READ timeout may retry once. Context/scope,
  node/dependency, and provider identity changes require review. Pre-execution
  material refusals use the coordinator and retain audit/log/feedback. The
  coordinator checks the envelope again after approval and before launch;
  existing restrictions are composed and restored, never replaced by a weaker
  check. An unavailable launch validator fails closed. Terminal
  errors omit raw exception strings. Scope and destructive authority are reset
  to the bound task on each model stage.
- Handoff: the runner refreshes durable state between nodes, carries at most
  eight completed dependency evidence references forward, and rejects unfinished
  dependencies. Completed, interrupted, and review-paused stages never replay
  automatically. Typed Active records persist through the operational store;
  evidence remains in the protected local store.
- Files: `src/decode/workflows/{agent_executor,models,runner,__init__}.py`,
  `src/decode/runtime/{agent_loop,coordinator}.py`, `src/decode/universal_agent.py`,
  `src/decode/schema/task_state.py`, `tests/test_workflows.py`,
  `tests/test_agent_loop.py`, `tests/test_governance.py`, canonical
  brain/workflow/build/test docs, root
  README/ROADMAP/AGENTS/CHANGELOG, and this ledger. Preserve all earlier Phase 2
  verifier/schema/store/planner/memory-documentation edits.
- Validation: final complete Windows `wenv` run with live Kali WSL and cached,
  network-isolated Docker passed (557 passed, 10 skipped, 55 subtests).
  Final direct Kali full suite after recovery passed (559 passed, 8 skipped,
  45 subtests). Repository Ruff lint and formatting passed (247 Python files);
  relative Markdown links across 54 files and `git diff --check` passed.
  Final Windows/live-WSL full run passed (554 passed, 13 skipped, 50 subtests).
  An earlier Windows live WSL/Docker run passed (552 passed, 10 skipped,
  55 subtests) before the final
  guards. A subsequent live run failed infrastructure checks: Kali returned
  `Wsl/Service/E_UNEXPECTED`, and Docker returned Desktop unable to start
  (5 failures, 553 passed, 10 skipped, 51 subtests). No failure was masked or
  relabeled as success. Kali and Docker subsequently recovered as described
  below, and the unchanged failing checks passed in the final full run.
  An intermediate offline
  Windows run passed (550 passed, 16 skipped, 45 subtests); one final callback
  preservation regression was added afterward.
- Docker: the installed Desktop engine was stopped and was started for the
  gate. Existing `decode-conformance:local` and `debian:bookworm-slim` images
  are reused; no new image, pull, installation, or network target is needed.
  A read-only health check reported Desktop unable to start; its CLI status
  then reported stopped. A bounded start was attempted without stopping WSL
  or other processes; it returned "Docker Desktop is already running", which
  does not establish engine health. `docker info` still reported Desktop
  unable to start and Desktop status remained stopped. The user subsequently
  explicitly authorized restarting WSL and Docker. `wsl --shutdown` completed;
  the installed Desktop lifecycle restart was requested with a bounded timeout.
  Desktop recovered and reports engine 29.8.0. The next all-live run passed
  Phase 2 WSL/Docker stage conformance but one existing Phase 1 WSL lifecycle
  check hit `Wsl/Service/CreateInstance/E_UNEXPECTED` (1 failed, 556 passed,
  10 skipped, 55 subtests). That exact check passed after a Kali health preflight
  (1 passed). The complete all-live suite then passed without modifying or
  skipping the check (557 passed, 10 skipped, 55 subtests).
  One stopped fixture container from the interrupted test
  run, `0dc42e6d4622`, was inspected: cached Debian image and exact command
  `/usr/bin/printf decode-phase1-ok`. It was removed with non-force `docker rm`;
  `docker ps -a` is now empty. It can be recreated by the conformance test.
  No images, project files, or evidence were removed. Low available host memory
  was observed, but it is not
  established as the cause of the service failures.
- Limits: model-free execution is a programmatic six-READ-capability API, not
  a new CLI selector or network/WRITE action family. File criteria prove
  observed presence/content, not WRITE-origin, semantics, finding confirmation,
  or continuing integrity. Cross-node recovery, general validators, retrieval
  adapters, runtime FSM, Core strategy, and workflow v2 remain later work.
- Migration/rollback: missing escalation on legacy incomplete Active records
  loads as `legacy_unclassified`. Completion must have protected evidence;
  malformed or unproven records fail validation rather than infer success.
  No database migration or dependency was added. Preserve operational-store
  backups before any future schema rollback; never erase evidence or replay
  interrupted/review-paused nodes to repair a checkpoint.
- Uncommitted work: all Phase 2 changes remain in `feat/working`.
  This closure request did not authorize shipping; the later shipping-review
  entry records the user's subsequent commit/PR authorization and blocker.
- Next action: start Phase 3 Core intent/workflow/criteria
  selection with a public reason and bounded delegation; Core cannot execute.
  WRITE-origin attestation is later evidence/workflow depth, not a substitute
  for Phase 3. No AWS account/region/services are chosen.
- Required input: none for Phase 2. The user explicitly authorized the WSL and
  Desktop restart; further unrelated repair or cleanup is not authorized.
  WSL startup was intermittent on this host, so preflight provider health on
  later live runs and preserve failures rather than infer missing tools or
  successful execution. No resource-tuning or all-distro reliability claim is
  made. AWS remains Deferred.

## Phase 2 first slice — verification truth and knowledge direction

The governed `ToolUseLoop` now checkpoints `TaskStatus.BLOCKED` and returns
`stopped=verification_failed` plus failed criteria when the verifier rejects a
final answer after the bounded replan allowance. The model's final answer is
not accepted as success. The workflow adapter already maps non-final stops to
unsuccessful stages. Focused verifier/loop tests passed (34 passed, 2 skipped)
before the reviewer-exhaustion case was added. Full Windows `wenv` tests passed
(503 passed, 14 skipped, 39 subtests); direct Kali WSL tests passed (511 passed,
6 skipped, 39 subtests). Ruff lint and diff checks passed; the final format
check follows the documentation update.
This closes one false-success path; typed Active Brain outcomes, deterministic
model-free stage execution, and recovery policy are still Target. The current
verifier accepts when no completion conditions are declared, and the optional
reviewer-model verifier accepts unavailable/unparseable reviewer responses;
neither is a general proof of task completion. The next Phase 2 slice should
bind explicit criteria to one authorized node and return typed completion or
escalation without giving the model a new execution path.

The accepted knowledge-layer direction is SQLite-first and project-scoped,
with optional read-only Obsidian-compatible Markdown notes. Memory, verified
knowledge, and reasoning remain distinct; UTOS budgets retrieval but does not
own or authorize it. No vault was accessed, synced, or created. Before broader
graph traversal, validate both edge endpoints share the declared project; the
current edge writer lacks that check. Dedicated graph databases and embeddings
remain Research, not Phase 2 dependencies.

## Phase 2 next slice — bounded stage completion and escalation

The existing workflow stage adapter now derives explicit `at_least`
completion criteria from the stage's minimum successful actions and protected
evidence requirements and passes them into `UniversalAgent.run_tool_loop`.
The deterministic verifier counts successful observations and evidence
artifacts with both id and hash; a missing or premature result cannot be
accepted by the model's final answer. The post-stage gate remains independent.
`StageResult` now carries a typed Completed/NeedsReplan/Blocked/Failed outcome,
rejects a contradictory success flag, and returns failed criteria. Exhausted
verification and budget stops become manual-review checkpoints in the workflow
runner, leaving dependent stages unrun. No second execution path was added.
Same-session resume rejects changed completion criteria. Focused tests cover
criterion boundaries, actual loop binding, the adapter, gate, and blocked
checkpoint. The operational TaskState store still strips observation data;
failed-criterion details are available in the immediate stage result, while
the persisted workflow has only a bounded summary and declared conditions.

Remaining Phase 2 work: objective/deliverable verification beyond count and
evidence presence; a model-free stage path; bounded context, safe recovery,
and an Active Brain outcome independent of this workflow Bridge. Do not
automatically replay a `needs_review` stage or treat reviewer-model availability
as a safety gate. Validation on 2026-09-27: focused verifier/workflow/agent-loop
tests passed (48 passed, 2 skipped) before the final checkpoint regression
case; native Windows `wenv` full suite passed (511 passed, 14 skipped,
39 subtests); direct Kali WSL full suite passed (519 passed, 6 skipped,
39 subtests). Repository-wide Ruff lint and format
checks passed, as did `git diff --check`. No live Docker suite was rerun because
this slice does not change provider execution. The work remains uncommitted;
preserve the prior Phase 2 documentation and verifier edits along with this
slice. Next: a model-free, single-stage path with typed context and bounded
recovery that still invokes only the existing governed coordinator.

## Phase 2 model-free READ slice

`ReadStageAction` is an explicit, typed action envelope bound to workflow
name/version and stage. `GovernedReadStageExecutor` takes a durable TaskState,
compares session/target/stage context, builds a target-scoped governance gate
and filesystem-scoped `HostController`, then performs one supported READ host
action with no model call. Its narrow set is `file_read`, `file_list`,
`file_search`, `process_list`, `service_status`, and `list_tools`; shell commands,
writes, network requests, and human stages are not accepted. At most one
automatic retry is allowed, and only after a timeout. A denial never retries.
An executor instance refuses a second invocation after its first attempt.
The existing coordinator owns telemetry, audit, and protected evidence. A
successful operation still pauses as `NeedsReplan` if the stage gate is unmet;
the workflow runner fences dependent stages. Failed attempts may also produce
protected evidence, but are never counted as successful actions. This path is
programmatic, not yet a CLI option, and does not implement the full Active Brain.

Tests cover in-scope execution with evidence/log/audit/feedback, out-of-scope
failure, unmet gate, timeout-only retry, denial without retry, envelope
binding, and one-shot invocation. Focused workflow tests passed (17).
The full native Windows `wenv` suite passed (516 passed, 14 skipped, 39
subtests); direct Kali WSL passed (524 passed, 6 skipped, 39 subtests).
Repository-wide Ruff lint/format, `git diff --check`, and changed-document
relative links passed. No live Docker run was repeated because provider
execution code did not change. No branch, commit, push, or PR was made;
preserve all prior uncommitted Phase 2 work. Next: context assembly and safe
recovery for a broader one-node Active Brain contract. AWS remains Deferred.

## Phase 2 bounded context and retry-truth slice

`BoundStageContext.from_task` now compares session, objective, workflow
name/version, target, and full stage metadata with the durable `PlanGraph`
before either stage executor acts. It keeps at most eight prior results and
redacts/truncates their summaries/finals. The governed agent prompt also bounds
guidance, instructions, deliverables, objective, and title. These observations
do not grant authority. Model-free READ actions accept only bounded JSON
parameters and retry only when `ExecutionStatus.TIMEOUT` and
`ExecutionErrorCategory.TIMEOUT` agree; an action change before or after an
attempt blocks recovery. Cancellation, denial, missing dependency, and
telemetry failure do not retry. An action's attempt count also cannot exceed
the stage step budget. The existing coordinator still owns all
execution and evidence. Model-free preflight refusals now enter that
coordinator as blocked, non-executing requests to preserve denial telemetry.
Focused workflow tests cover context rejection,
bounded/redacted prompts, ambiguous timeout rejection, and action mutation
during recovery, plus a stage-budget bound. No new execution path or automatic
stage replay was added.

This remains a Bridge, not a general Active Brain: full context retrieval,
model-free security/network actions, cross-node recovery, and independent
objective validation remain Target. No branch, commit, push, or PR was
requested. The next implementation boundary is a typed Active node with
context/evidence provenance and a deterministic completion contract. AWS
remains Deferred.

Validation on 2026-09-29: focused workflow tests passed (21); full native
Windows `wenv` suite passed (520 passed, 14 skipped, 39 subtests), and direct
Kali WSL passed (528 passed, 6 skipped, 39 subtests). Repository-wide Ruff
lint/format, `git diff --check`, and changed-document relative links passed.
No live Docker run was repeated because execution-provider code did not
change. Preserve all uncommitted Phase 2 work. Next: a reusable typed Active
node boundary with provenance-bearing context/evidence and stronger
deterministic objective criteria; do not present this Bridge as complete v2.

## Phase 2 typed Active READ result and file-digest criterion

The model-free `GovernedReadStageExecutor` now emits an `ActiveNodeResult` for
attempted READ stages. The result binds session, node, workflow fingerprint,
node material fingerprint, outcome, gate decision, attempt count, and per-attempt
request IDs, capability, provider, status, and protected evidence reference.
Only a known `file_sha256` signal may enter the typed record; raw file content
and paths do not. `TaskState.active_nodes` persists and validates that record
on reload. The workflow runner checks its node binding and gate agreement
before checkpointing it; a mismatch pauses the stage and does not store the
untrusted Active result.

`WorkflowGate.expected_file_sha256` is an optional exact lowercase SHA-256
criterion. It requires a successful, protected-evidence-linked governed
`file_read` observation with that digest. A model summary, generic evidence
link, malformed digest, or successful read of different bytes cannot satisfy
it. This is an exact observed-file check, not general objective validation,
finding confirmation, or a model-free network/security action. Preflight
denials still cross the coordinator but do not yet produce an Active-node
record; model-driven stages also do not yet produce this typed record.

Files in this slice: `src/decode/schema/{task_state.py,__init__.py}`,
`src/decode/workflows/{models.py,agent_executor.py,runner.py}`,
`tests/test_workflows.py`, `docs/{BUILD_PLAN.md,BRAIN_ARCHITECTURE.md,WORKFLOWS.md,CONTINUATION.md}`,
and `CHANGELOG.md`. All other modified files are prior uncommitted Phase 2
work and must be preserved. No commit, push, branch, PR, or AWS action was
requested.

Validation on 2026-09-29: focused workflow suite 26 passed; full native
Windows `wenv` suite 525 passed, 14 skipped, 39 subtests; direct Kali WSL
suite 533 passed, 6 skipped, 39 subtests. Repository-wide Ruff lint and format
passed. No live Docker retest was run because provider behavior did not change.
Next: carry trusted, typed observations through the general Active node path
and add deterministic validators for more than a single file digest while
preserving the one governance gate and bounded recovery. Phase 2 remains a
Bridge in progress; AWS remains Deferred.

## Phase 2 model-driven provenance and paired file-metadata gate

`UniversalAgent.run_tool_loop` now offers an internal coordinator-result
callback. `GovernedAgentStageExecutor` projects each actual governed result
through the same allowlisted `ActiveObservation` contract used by the model-free
READ executor. Workflow action and evidence counts come only from these
captured results, not model step text or task-artifact summaries. The typed
`ActiveNodeResult` is bound to the durable workflow/node fingerprints and
persisted in `TaskState.active_nodes` when a governed action occurred. A
model final answer after only unsuccessful governed actions becomes
`NeedsReplan` and pauses for review, even when a final-answer-only gate would
otherwise pass. The universal loop also requires the coordinator success flag
and inner operation success before presenting an action as successful.

`WorkflowGate.expected_file_size_bytes` adds a strict non-negative byte-length
criterion to exact file SHA-256. Both require a successful protected-evidence-
linked governed `file_read`; when both are configured, one observation must
match both. Only SHA-256 and bounded decimal byte length enter the typed
signals; file paths/content and free-form normalized output do not. A model
summary, spoofed loop step, loose artifact, or two different reads cannot
satisfy the paired criterion.

Changed this slice: `src/decode/universal_agent.py`,
`src/decode/schema/task_state.py`,
`src/decode/workflows/{agent_executor.py,models.py}`,
`tests/test_workflows.py`, `docs/{BUILD_PLAN.md,BRAIN_ARCHITECTURE.md,WORKFLOWS.md,CONTINUATION.md}`,
and `CHANGELOG.md`. Preserve all earlier uncommitted Phase 2 edits. No new
execution route, network action, branch, commit, push, PR, or AWS action was
introduced. Model-only stages with no governed action still have no typed
Active result; arbitrary deliverables, cross-node context/recovery, and the
full Active Brain remain Target.

Validation on 2026-09-29: focused workflow/loop suite 55 passed, 2 skipped;
full native Windows `wenv` suite 530 passed, 14 skipped, 39 subtests;
direct Kali WSL suite 538 passed, 6 skipped, 39 subtests. Repository-wide
Ruff lint and format passed. No live Docker rerun was needed because provider
behavior did not change. Next: define bounded general Active-node context and
recovery policy with typed escalation, then extend deterministic validators
to explicit artifacts/deliverables without treating model prose as proof.

## Phase 2 bounded dependency context and typed escalation

`BoundStageContext` now carries up to eight protected evidence references from
completed dependency nodes. Each source Active result must match session,
workflow fingerprint, node fingerprint, successful outcome, and a successful
evidence-linked observation. Reference IDs and other provenance identifiers
are length-bounded. The model prompt receives those references as observations,
not authority or raw evidence. Stale/mismatched dependency records are ignored.

`ActiveObservation` records the coordinator's stable error category. Every new
incomplete `ActiveNodeResult` has an `ActiveEscalation` with a stable category
and, when applicable, an observed governed request ID. The bridge classifies
approval, policy, dependency, timeout, cancellation, telemetry/safety,
verification, budget, execution failure, and material-action change without
granting permission or initiating recovery. Preflight READ refusals that have
a valid stage binding and action-change refusals retain a typed blocked result
with the refusal request. A mutation after an attempted READ preserves both
the prior attempt and blocked refusal. The only automatic retry remains the
previously bounded unchanged READ action with matching timeout status/category.
Context mismatch without a valid node binding remains a blocked stage result
without a bound Active record.

`TaskStateStore.load` labels previously saved incomplete Active results lacking
this new field `legacy_unclassified` rather than inventing a cause or making
old sessions unreadable. New incomplete records missing an escalation fail
schema validation. Tests cover categorized denial/approval/budget, mutation
provenance, bounded dependency evidence, stale fingerprints, required request
binding, oversized IDs, and legacy load/save.

Changed this slice: `src/decode/schema/{task_state.py,__init__.py,store.py}`,
`src/decode/workflows/{models.py,agent_executor.py}`,
`tests/{test_workflows.py,test_task_state.py}`,
`docs/{BUILD_PLAN.md,BRAIN_ARCHITECTURE.md,WORKFLOWS.md,CONTINUATION.md}`,
and `CHANGELOG.md`. Preserve all earlier uncommitted Phase 2 edits. No new
file, execution route, model-free network action, branch, commit, push, PR, or
AWS action was introduced.

Validation on 2026-09-29: focused workflow/task-state suite 47 passed; full
native Windows `wenv` suite 534 passed, 14 skipped, 39 subtests; direct Kali
WSL suite 542 passed, 6 skipped, 39 subtests. Repository-wide Ruff lint and
format passed. No live Docker rerun was needed because provider behavior did
not change. Next: add one deterministic, evidence-bound artifact/deliverable
criterion beyond file metadata, keeping findings unconfirmed until separately
verified. General Active recovery and cross-node strategy remain Target; AWS
remains Deferred.

## Phase 2 exact file-artifact deliverable criterion

`WorkflowGate.expected_file_path` may now declare an absolute native path only
when an exact `expected_file_sha256` is also declared. The path is normalized
in the workflow spec. The post-stage gate accepts only one successful,
protected-evidence-linked governed `file_read` with the matching canonical
path fingerprint and content SHA-256; declared byte length must match the
same observation. The shared result projector stores only `file_path_sha256`
alongside the existing allowlisted digest and byte-length signals, never the
raw path or file content in the Active record. Both model-free and model-driven
stage adapters use this projection and the same deterministic gate. A file with
identical bytes at a different path, split signals across reads, unprotected
observations, malformed paths, and model assertions fail the artifact gate.

This is a narrow proof of a file reported at a declared path with expected
bytes during a governed read. It does not prove the stage created the file,
the contents are semantically correct, or the file remains unchanged after
the read. It does not infer WRITE approval or confirm any security finding.
No new execution path, external target action, or automatic retry was added.

Changed this slice: `src/decode/workflows/{models.py,agent_executor.py}`,
`src/decode/schema/task_state.py`, `tests/test_workflows.py`,
`docs/{BUILD_PLAN.md,BRAIN_ARCHITECTURE.md,WORKFLOWS.md,CONTINUATION.md}`,
and `CHANGELOG.md`. Preserve all earlier uncommitted Phase 2 changes. No new
file, branch, commit, push, PR, or AWS action was requested.

Validation on 2026-10-01: focused workflow/task-state suite 49 passed;
full native Windows `wenv` suite 536 passed, 14 skipped, 39 subtests;
direct Kali WSL suite 544 passed, 6 skipped, 39 subtests. Repository-wide
Ruff lint and format passed. No live Docker rerun was needed because provider
behavior did not change. Next: evaluate a separate governed WRITE-origin
attestation plus post-read verification for produced artifacts, with explicit
approval and no assumption that a read proves creation. General Active
recovery and semantic deliverable validation remain Target; AWS Deferred.

## Deferred decisions

FSM library, NetworkX role, API auth/lifecycle, TS packaging/deprecation,
browser authenticated-session storage, and AWS topology/services/region/budget.

## Validation at handoff

- Documentation whitespace/diff check: passed.
- Relative Markdown links across 54 root/docs files: passed.
- All root Markdown files have headings and v2-aligned responsibilities: passed.
- Windows `ruff check --no-cache .`: passed; Kali WSL lacks Ruff and no
  dependency was auto-installed.
- Focused final host/session contract suite: 60 passed, 8 skipped, 3 subtests
  passed.
- Native Windows `wenv` (Python 3.12.0) editable install: `pip check` passed;
  full suite 475 passed, 10 skipped, 30 subtests passed.
- Kali WSL `python -m pytest -p no:cacheprovider tests/`: 483 passed, 2 skipped,
  30 subtests passed.
- Phase 1 governance/host focused suite before the final path validator:
  64 passed, 5 subtests passed; the complete final suites include the new path
  validation test.
- Live provider check from Windows: Decode discovered `/usr/bin/uname` as
  `wsl/kali-linux` and executed it through the same provider (`Linux`).
- Current mapping slice: Windows Ruff passed; full Windows suite 478 passed,
  10 skipped, 34 subtests passed; Kali WSL suite 486 passed, 2 skipped,
  34 subtests passed. A configured `wsl/kali-linux` mapping resolved
  `E:\hackagent` to `/mnt/e/hackagent`; the Kali path exists. An absent
  optional executable remained absent. Docker daemon conformance is blocked
  because the Docker API pipe is unavailable; no installation was attempted.
- Exact executable inspection slice: Windows Ruff passed; full Windows suite
  483 passed, 10 skipped, 34 subtests passed; Kali WSL suite 491 passed,
  2 skipped, 34 subtests passed. A governed live lookup in `wsl/kali-linux`
  returned `/usr/bin/uname` with a SHA-256 fingerprint. Docker daemon remains
  unavailable; no Docker conformance claim is made. A partial PATH scan now
  fails closed with raw output preserved.
- Executable binding slice: Windows Ruff passed; full Windows suite 485 passed,
  10 skipped, 34 subtests passed; Kali WSL suite 493 passed, 2 skipped,
  34 subtests passed. Focused governance/host coverage passed with 100 tests,
  2 skipped, and 8 subtests. A governed live `wsl/kali-linux` command bound
  `/usr/bin/uname` and its SHA-256 in approval, rechecked it, and executed that
  path successfully (`Linux`). Exact lookup now tests ordered PATH candidates
  directly, so stale inherited Windows PATH directories do not force a partial
  inventory scan. Docker remains unavailable and was not installed.
- Local session binding slice: Windows Ruff passed; focused local/session suite
  40 passed; full Windows suite 489 passed, 10 skipped, 34 subtests passed;
  Kali WSL suite 497 passed, 2 skipped, 34 subtests passed. Tests cover approval
  identity, `cd` state, relative outputs, missing dependencies, executable
  replacement, and context change before launch. A session must start in an
  authorized read root; the old implicit-cwd test now opens it explicitly.
- Docker outcome conformance slice: Ruff passed; focused execution suite
  50 passed, 22 subtests passed. Full Windows suite 491 passed, 12 skipped,
  39 subtests passed; Kali WSL suite 499 passed, 4 skipped, 39 subtests passed.
  Opt-in live `wsl/kali-linux` process check passed (1 test, 3 subtests):
  success, non-zero exit, and missing command. Docker health returned false;
  live Docker was not run, and no image was pulled or tool installed.
- Docker Engine recheck on 2026-09-24: `DockerExecutor.check_health()` returned
  true, but the same SDK daemon has zero images and zero containers. The live
  Docker test was not run because it requires an existing image and must not
  auto-pull one. This historical prerequisite was resolved by the next item.
- User-authorized image creation on 2026-09-24: pulled official `busybox:1.38`
  (base digest `sha256:fd7dc98638c8e305f4dc34e979f1c0fdfdcaeb0fbf8fcff77ae834b6da3d7e6e`)
  and built local-only `decode-conformance:local` (image ID
  `sha256:3a68d3162e1bcffbb59299e578de3c9625836f57f4bbc5bfe99b553b860f2da2`)
  from an inline Dockerfile with labels; no repository file was added. The
  initial live check found that SDK `run()` leaked a created container on start
  failure; the exact empty test container was verified and removed. The provider
  now uses explicit create/start/cleanup. Opt-in live Docker conformance passed
  (1 test, 3 subtests), including success, non-zero exit, missing command,
  missing image without pull, and zero remaining containers. The test image is
  local to this Docker Engine and is not a release image.
- Final validation after the Docker lifecycle fix: Windows Ruff, Markdown links
  across 54 files, and `git diff --check` passed. The full Windows suite with
  live Docker enabled passed (494 passed, 11 skipped, 42 subtests); the full
  Kali WSL suite passed (501 passed, 4 skipped, 39 subtests). The image remains
  cached and `docker ps -a` shows no containers. No commit or push was made.
- Phase 1 governed-task release gate on 2026-09-24: the final Windows `wenv`
  suite with live `wsl/kali-linux` and Docker process/governed-task opt-ins
  passed (504 passed, 10 skipped, 45 subtests). The final direct Kali Linux
  suite passed (508 passed, 6 skipped, 39 subtests). Local, WSL, and Docker
  governed tasks each discovered a provider tool, executed a command, saved
  balanced SQLite checkpoints and protected hashed evidence, produced log,
  audit, and feedback records, then resumed without replaying the command.
  Repository Ruff and `git diff --check` passed. Kali has no Ruff binary, and
  none was installed. `debian:bookworm-slim` was cached locally with image ID
  `sha256:3783cc01769c7b2b1b83a5c5ad96c815348e28ed7da68e2e3687004faa906251`;
  Docker shows zero leftover containers. No commit or push was made.
- Pre-PR rerun on 2026-09-27: Windows Ruff passed; direct Kali WSL suite passed
  (508 passed, 6 skipped, 39 subtests). Docker Desktop was initially stopped,
  so an early opt-in Windows run failed its two live Docker tests; one unrelated
  discovery test also failed under simultaneous Windows/Kali runs but passed
  alone. After starting the installed Docker Desktop engine, the serial full
  Windows suite with live WSL and Docker opt-ins passed (504 passed, 10 skipped,
  45 subtests). The serial Windows suite without live Docker also passed
  (502 passed, 12 skipped, 42 subtests). No code workaround was made for the
  unavailable engine or the transient test failure.
- PR #20 CI remediation on 2026-09-27: Ruff formatting was applied to the 20
  files rejected by `ruff format --check .`. The Bandit job reported three
  medium-severity B608 findings in SQLite artifact INSERT, SELECT, and UPDATE
  statements, not shell execution or high-severity issues. Those statements
  now use fixed SQL syntax and bound values; a SQL-metacharacter regression
  test was added. Local Ruff lint/format checks passed. Focused memory tests
  passed (30); the full Windows suite with live WSL/Docker passed (505 passed,
  10 skipped, 45 subtests), and direct Kali WSL passed (509 passed, 6 skipped,
  39 subtests). Bandit is not installed locally and was not auto-installed.
  PR #20 CI run `36331153673` passed the Bandit security, Ruff lint/format,
  build, and Python 3.11/3.12 test jobs.
- `git diff --check`: passed (line-ending notices only for untouched CRLF files).

The completed Phase 1 work spans the execution-provider/session
contract, built-in providers, host output/session controller binding, typed
resolved-action coordinator/exports, capability descriptions, execution,
governance, host/test modules, automatic task-state checkpoint/resume and
sanitized storage, and the corresponding build-plan, pipeline, host-control,
test-strategy, continuation, and changelog documentation. Phase 1 PR #20 is
merged. Preserve the uncommitted Phase 2 work when resuming; no new branch,
commit, push, or PR was requested for this slice.

The repository now has an ignored native Windows virtual environment at `wenv`.
Its editable `decode` import resolves to `E:\hackagent\src\decode`; activate it
with `.\wenv\Scripts\Activate.ps1`. The machine-wide `python` command may still
resolve an older editable worktree, so use `wenv` for native Windows work.

Windows validation also closed three portability gaps: protected evidence now
uses a current-user-only DACL instead of POSIX mode-bit assumptions; the MCP
server writes audit/log/feedback/evidence under configured runtime paths; and
SQLite breaks equal session timestamps by insertion order. Windows tests close
SQLite stores before temporary-directory cleanup.

The Codex sandbox helper still fails to initialize in this session. Changes were
applied with the same patch helper under approved elevated execution. The
recoverable helper backup remains at
`C:\Users\ab712\.codex\.sandbox-bin.backup-20260918`.

## Handoff template

```markdown
### Handoff YYYY-MM-DD HH:MM TZ
- Objective:
- Files changed:
- Tests/results:
- Decisions:
- Risks:
- Uncommitted work:
- Next action:
- Required input/approval:
```

The user will create AWS later. Do not invent account, region, domain, network,
budget, or services. A future RFC maps stable local contracts.
