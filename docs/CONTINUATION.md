# De-code v2 Continuation Ledger

**Updated:** 2026-09-18
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
   and cross write scope. External-provider outputs fail closed pending mapping.
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

## Next slice — Phase 1 stable execution kernel

```text
EnvironmentProvider contract
 -> provider filesystem/cwd/env and output mapping
 -> provider-native stateful sessions
 -> resolved action identity/version/side effects
 -> local Linux + WSL + Docker conformance
```

Keep external-provider output commands and sessions fail-closed until those
contracts and conformance tests exist. Do not infer semantic browser/search from
an installed executable.

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
  full suite 445 passed, 10 skipped, 22 subtests passed.
- Kali WSL `python -m pytest -p no:cacheprovider tests/`: 453 passed, 2 skipped,
  22 subtests passed.
- Live provider check from Windows: Decode discovered `/usr/bin/uname` as
  `wsl/kali-linux` and executed it through the same provider (`Linux`).
- `git diff --check`: passed (line-ending notices only for untouched CRLF files).

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
