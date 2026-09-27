# Host and Environment Control

**Status:** Current host operations and system-tool provider binding

Host control exposes governed file, process, service, command, session, and
discovery capabilities. It is kernel functionality, not a plugin.

Current capabilities include file read/list/search/write/edit/fetch, process and
service operations, `list_tools`, command, and sessions. Local discovery scans
the Decode process PATH. With `DECODE_EXECUTOR=wsl/<distribution>`, discovery
enumerates that distribution's PATH and `shell_command` uses the same provider
instance. Command strings split to argv without a shell.

## Semantics

- Command is not a shell; reject pipes, redirects, `&&`, `||`, substitution.
- Non-zero exit is failure unless declared.
- Unknown params fail validation.
- File-producing options require WRITE and output scope.
- Recognizable network commands and URL-bearing argv bind a target into the
  engagement allowlist before execution.
- UI success reflects result, not process creation.

## EnvironmentProvider

```text
identify()  discover()  execute(argv)  scoped read/write()  health()
```

The first Phase 1 slices expose immutable provider identity, capabilities,
filesystem mode, path mappings, and a typed execution context. Local is
`shared`; WSL and Docker are `mapped`; SSH is `remote`; MCP is `none`. Path
resolution selects the most-specific configured host root, rejects unmapped
paths, and rejects writes through read-only mappings. These transport mappings
do not grant scope.

Local Linux and explicit WSL distributions currently bind system-tool discovery
and execution. Configured WSL, Docker, and SSH providers bind supported
cwd/environment/output declarations into their native transports; Docker also
mounts configured roots. MCP remains an external semantic-tool provider, not a
host PATH provider. Provider-bound sessions are context-persistent rather than
raw PTYs: local, WSL, and SSH preserve validated cwd/environment across commands;
Docker and MCP do not declare session support.

Inside Kali, local means Kali. From Windows, `wsl/kali-linux` must own both
discovery and execution. Installed Kali does not expose its PATH to Windows.

Chromium/Firefox executables are not semantic browser/search tools. Providers
must expose navigation/rendered DOM/download scope/auth session references/
sources/evidence. Cookies/secrets remain credential references.

The current semantic boundary is strict: only an explicitly listed provider tool
may be called. A required `url`, `target`, `domain`, `host`, `ip`, `cidr`, or
`network` field makes target scope mandatory; any supplied target is checked.
HTTP/browser downloads must declare WRITE risk and a scoped output before a
future provider may enable them. Native semantic HTTP/browser/search providers
are not yet implemented.

For non-local providers, output-producing CLI commands require every classified
host output to cross filesystem WRITE scope and an explicit writable provider
mapping. The controller rewrites only the classified output arguments and binds
both host and provider paths into the approval request. Commands without a full
mapping are denied. A provider session binds its immutable ID, exact provider,
host/provider cwd, and mapped outputs into every action. Scope, mapping, policy,
and provider identity are rechecked immediately before each command; cd verifies
the provider directory before changing state. Providers without the session
capability are denied without local fallback. Session lifecycle arguments are
strict, starting cwd and explicit outputs cross filesystem scope, and network
commands are denied inside sessions; use `shell_command` with an explicit target
so the engagement allowlist is enforced.

Plan denies; Ask allows verified READ and prompts WRITE/DESTRUCTIVE; Auto may
allow scoped WRITE but never bypass destructive control. Sessions retain cwd and
allowlisted env, but every command is independently governed.

Governed CLI and provider session commands now carry a typed resolved action.
Its approval-bound fields include exact provider argv, target, cwd, mapped
outputs, known side effects, timeout, and evidence/parser policy. Audit, logs,
and feedback retain a summary without raw argv or path values. Unverified tool
versions and unclassified inputs/side effects remain explicitly unknown.
Unknown CLI effects and session state changes require at least WRITE risk.

# Executable inspection

`list_tools` accepts an optional `exact` executable basename. An exact match
returns its path and SHA-256 content fingerprint from the selected provider;
an absent executable returns an empty list. The fingerprint is content identity,
not a semantic version. Provider discovery reads only `PATH`, not the full
environment, and rejects relative or malformed PATH entries. This inspection
is a governed READ action. Broad scans retry with existing provider-side PATH
directories when a stale directory makes the initial scan fail. A scan that
still fails reports partial output rather than silently claiming a complete
inventory. The current external-provider discovery implementation needs GNU
`find -printf` plus `/usr/bin/printenv`, `test`, and `sha256sum`; BusyBox-only
images are not a supported governed-tool test environment yet.

Before `shell_command` or any `session_exec` reaches approval,
Decode resolves every executable stage to an absolute provider path and hashes
its content. This includes both `sudo` and the command it wraps. Target scope,
command policy, and filesystem output scope run before provider inspection. The
resolved argv, path, and digest are approval-bound; immediately before launch,
Decode hashes the same absolute path again and denies execution if it changed.
Missing executables become a typed missing-dependency block and are never
installed automatically. Audit/log/feedback summaries record only verification
state and executable count, not paths or hashes. Semantic version remains empty
until a separate safe, tool-aware version contract exists. Local sessions
resolve against their captured PATH and bind the environment hash, cwd, and
declared output paths to approval. A local `cd` binds its next cwd as a session
state transition without inventing an executable. A changed executable or
session context blocks launch.
