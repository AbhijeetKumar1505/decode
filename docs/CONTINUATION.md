# De-code v2 Continuation Ledger

**Updated:** 2026-09-27
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

Current worktree also has `src/decode/workflows/`, workflow playbooks, CLI
integration, and `tests/test_workflows.py`. Preserve these as Phase 4 Bridge.

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

Phase 1's local Linux/Kali WSL/Docker task gate is met. The implementation is
being delivered from `feat/working` in a pull request against `main`:

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

Next is Phase 2 Active Brain: bind one authorized operation to typed local
completion/escalation, deterministic recovery, and evidence. A separate
hardening slice may address semantic tool-version attestation, arbitrary CLI
input/side-effect declarations, and stronger Docker image identity binding.

Keep Docker/MCP sessions and any provider without an explicit session capability
fail-closed. Keep cwd/output actions fail-closed when no explicit mapping covers
them. Live Docker process-outcome and governed task lifecycle conformance
passed. Do not infer semantic browser/search from an installed executable. A
content fingerprint does not attest to an
external interpreter or shared libraries.

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
- `git diff --check`: passed (line-ending notices only for untouched CRLF files).

The completed Phase 1 work spans the execution-provider/session
contract, built-in providers, host output/session controller binding, typed
resolved-action coordinator/exports, capability descriptions, execution,
governance, host/test modules, automatic task-state checkpoint/resume and
sanitized storage, and the corresponding build-plan, pipeline, host-control,
test-strategy, continuation, and changelog documentation. Phase 2 starts only
after the Phase 1 pull request is reviewed and merged; preserve any unmerged
work when resuming.

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
