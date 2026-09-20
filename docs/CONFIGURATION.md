# Configuration

**Status:** Current environment variables stay valid until versioned v2 config

Defaults are local, least-privilege, fail-closed. Precedence/source are visible.
Secrets use references, not committed files. Unknown keys fail typed validation.

```text
explicit task/CLI -> project -> user -> system -> safe defaults
```

Lower precedence cannot weaken policy.

Domains: runtime paths/storage/retention; API/auth; providers; all scopes;
permission/risk/approval/time/rate; models/data/locality; UTOS budgets/context;
workflow versions; memory/indexing; logs/audit/export/redaction.

Provider identity names the actual environment such as `wsl/kali-linux`.
Discovery, health, cwd, paths, and execution happen inside it.

Current system-tool selection accepts `DECODE_EXECUTOR=local`,
`DECODE_EXECUTOR=wsl/<distribution>`, and the compatibility spelling
`wsl:<distribution>`. A qualified WSL identity binds PATH discovery and command
execution to that distribution. External-provider output files and stateful
sessions are intentionally unavailable until provider filesystem/session scope
is implemented; there is no local fallback.

Search/HTTP/browser/auth sessions are explicit providers with network scope,
egress, download path, credential refs, evidence. Desktop browser tools are not
inherited.

Document secret variable names, not values. Validate late, inject only into the
operation, redact telemetry, preserve provider data policy.

Current `app/config.py` is present truth. Renames need typed config,
deprecation, migration, compatibility test, rollback. The future TS CLI consumes
API config views, not duplicate Python logic.
