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

Local Linux and explicit WSL distributions currently bind system-tool discovery
and execution. Docker and SSH use the execution interface but still need Phase 1
conformance for provider-scoped filesystem/session behavior. MCP remains an
external semantic-tool provider, not a host PATH provider.

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

For non-local providers, output-producing CLI commands and stateful host sessions
are denied rather than silently using local paths or local session state. Phase 1
adds the filesystem mapping and session transport needed to enable them safely.
Local session lifecycle arguments are strict, starting cwd and explicit outputs
cross filesystem scope, and network commands are denied inside sessions; use
`shell_command` with an explicit target so the engagement allowlist is enforced.

Plan denies; Ask allows verified READ and prompts WRITE/DESTRUCTIVE; Auto may
allow scoped WRITE but never bypass destructive control. Sessions retain cwd and
allowlisted env, but every command is independently governed.
