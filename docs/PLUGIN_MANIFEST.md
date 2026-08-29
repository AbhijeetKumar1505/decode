# Extensions and Plugins

## Status

**The in-tree plugin system has been removed.** `decode/tools.py`
(`PluginManager`/`ToolRegistry`) and `decode/plugins/` (the manifest, sandbox,
and lifecycle code, plus the bundled `recon`/`web`/`network`/`exploit` plugins)
were deleted during the universal-agent consolidation. They encoded the old
"tools are the architecture" model — hardcoded security tools shipped in-tree —
which the governed universal agent replaces with tool **discovery**
(`list_tools`) plus the governed `shell_command` capability.

There is no supported dynamic-plugin execution path today.

## How to extend Decode now

| Need | Mechanism |
|---|---|
| A repeatable procedure / workflow | **Markdown playbook** (`SKILL.md`) — see [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md). No Python. |
| A new OS primitive | Add it to `decode/hostcontrol/operations.py` and wire it through `HostAgent` as a first-class capability. |
| Drive any installed tool | `list_tools` to confirm it exists, then the governed `shell_command` capability. Nothing is hardcoded. |

## Future plugin surface (planned)

Per the De-code plan, *plugins* mean optional connectors to **external** systems
(issue trackers, cloud providers, hosted scanners, MCP servers) — never in-tree
security tools and never core OS operations, both of which are native
capabilities. Any future plugin surface must, before it is reintroduced:

- pass typed input and output through `ExecutionCoordinator` without broadening
  the caller's effective scope, approval, executor, credential, or model access;
- verify source and compatibility without importing untrusted entrypoints;
- run untrusted code under an isolation profile (e.g. a network-disabled,
  read-only, resource-limited container) with explicit, revocable enablement; and
- carry the same mandatory audit, logging, and feedback telemetry as every other
  governed execution.

Until a design meets that bar, extend Decode through native capabilities and
markdown playbooks only.
