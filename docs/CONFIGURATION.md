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
sessions require an explicit provider path mapping; there is no local fallback.

`DECODE_PROVIDER_MAPPINGS` is a JSON object keyed by the selected provider's
exact identity. Set it in the project `.env` or user environment. Each value is
an array of `{host_root, provider_root, writable, provider_style}` entries.
Roots must be absolute. `writable` defaults to false and `provider_style` to
`posix`. For example, with `DECODE_EXECUTOR=wsl/kali-linux` on Windows:

```text
DECODE_PROVIDER_MAPPINGS={"wsl/kali-linux":[{"host_root":"E:\\hackagent","provider_root":"/mnt/e/hackagent","writable":false}]}
```

Only the exact selected identity is applied; a mapping for another WSL distro,
Docker image, or SSH endpoint grants nothing. Invalid selected-provider
configuration stops initialization. Mapping does not itself authorize a path:
filesystem scope and per-command risk/approval still apply. Docker mappings
become container mounts; WSL/SSH mappings must reflect an existing path in that
environment. Do not include secrets in mapping configuration.

Search/HTTP/browser/auth sessions are explicit providers with network scope,
egress, download path, credential refs, evidence. Desktop browser tools are not
inherited.

Document secret variable names, not values. Validate late, inject only into the
operation, redact telemetry, preserve provider data policy.

Current `app/config.py` is present truth. Renames need typed config,
deprecation, migration, compatibility test, rollback. The future TS CLI consumes
API config views, not duplicate Python logic.
