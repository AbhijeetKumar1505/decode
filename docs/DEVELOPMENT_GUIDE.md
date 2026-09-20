# Development Guide

## Start

Read `AGENTS.md`, [BUILD_PLAN.md](BUILD_PLAN.md), and
[CONTINUATION.md](CONTINUATION.md). Inspect the dirty tree and preserve unfinished
work. Run native Windows portability checks in `wenv`, and run Linux-sensitive
development/tests in Kali WSL from `/mnt/e/hackagent`. Current `pyproject.toml`
is the dependency/runtime truth.

For the current Windows checkout:

```powershell
py -3.12 -m venv wenv
.\\wenv\\Scripts\\Activate.ps1
python -m pip install -e .
python -m pip install pytest mongomock ruff
ruff check --no-cache .
python -m pytest -p no:cacheprovider tests/
```

Keep `wenv/` untracked. Re-run the full Kali WSL suite after changes that affect
portable runtime behavior.

## Rules

- Model proposes; runtime authorizes/executes.
- Every external action crosses `ExecutionCoordinator`.
- Discovery and execution share a provider.
- Workflow procedure is declarative/versioned.
- Core cannot execute; Active cannot expand authority.
- Tools do not decide policy.
- Non-zero exit/failed criteria cannot be success.
- Evidence/events/audit/state are correctness.
- Do not create target packages ahead of phase.

## Change sequence

Identify phase/invariant; write failing tests; evolve typed contracts; implement
small vertical slice; migrate persisted state; verify failure/denial/timeout/
cancel/resume; update docs/ADR/continuation; review bypass/secrets/maturity.

Capabilities declare typed I/O, side effects, scopes, provider requirements,
risk, approval, timeout, idempotency, evidence, result. Resolve tools later; no
per-tool model logic or direct subprocess.

Bridge workflows use tested frontmatter/DAG/gates/persistence/resume. Target YAML
needs schema/version/migration tests and requests capabilities, not raw bypasses.

Model adapters normalize capabilities/usage/errors and support UTOS accounting.
Fallback cannot cross data policy or repeat tools.

Use typed error categories. Preserve actionable public details without secrets.
Use Current/Bridge/Target/Research/Deferred labels. Update continuation at pause.

Never reset user work. Review boundaries, safety, migration, truth, provider
identity, secrets, tests, docs, and rollback.
