# Extensions: MCP servers and plugins

De-code has three tool sources behind one capability registry — **native**
built-ins, **system** tools (discovered, shell-driven), and **external
providers** (MCP servers and plugin packages). This document covers the external
providers, owned by the extension layer in `decode/extensions/` and driven by the
`decode mcp …` and `decode plugin …` commands.

Installation, registration, and execution are three separate systems: installing
or registering an extension never runs anything; the agent only ever *selects*
already-registered capabilities, and every call still flows through
`ExecutionCoordinator` (scope, risk, approval, audit, evidence).

## Configuration scopes

State lives in three scopes with **project > user > system** precedence:

| Scope | Location | Override |
|---|---|---|
| user | `~/.decode/` | `DECODE_HOME` |
| project | nearest `./.decode/` | `DECODE_PROJECT_HOME` |
| system | `/etc/decode/` (POSIX) | `DECODE_SYSTEM_HOME` |

MCP servers are stored in `mcp.json`, plugins in `plugins.json`, per scope. A
project can enable or override an extension without touching user config.

## MCP servers

An MCP server is an external tool provider (a separate process or endpoint). It
is **not** a plugin and is never used to package system tools like `nmap`.

```bash
decode mcp add mongodb -- npx -y mongodb-mcp-server
decode mcp list
decode mcp disable mongodb        # kept, not started or exposed
decode mcp remove mongodb
```

At runtime the manager starts an enabled server lazily, calls `tools/list`, and
registers each tool as a capability namespaced by server (`mongodb.find`). Because
an MCP call is an opaque structured payload (not an argv), its risk cannot be
inferred — it is **declared** per server (`--risk read|write|destructive`) and the
governance gate uses that. Execution runs through the existing `MCPExecutor` under
the coordinator. A broken server is skipped, never blocking the others.

## Plugin packages

A plugin is a **declarative package**, never in-process code. Its skills run as
governed `shell_command` playbooks and its MCP servers as isolated external
processes, so there is no arbitrary-code-execution risk — the failure mode of the
removed in-tree loader.

```text
web-security/
├── manifest.json
├── skills/            # SKILL.md playbooks
├── mcp/servers.json   # MCP servers to register
├── commands/          # command docs (markdown)
└── agents/            # agent docs (markdown)
```

```json
{
  "name": "web-security",
  "version": "1.2.0",
  "description": "Web application security toolkit",
  "skills": ["skills"],
  "mcp": ["mcp/servers.json"]
}
```

```bash
decode plugin install ./web-security
decode plugin list
decode plugin disable web-security
decode plugin remove web-security     # also removes the MCP servers it added
```

Install **verifies the manifest and fails closed**: it rejects a missing
manifest, path traversal outside the package, non-markdown skill/command/agent
files, and non-JSON MCP entries. It then copies the package into the plugin store,
registers the package's MCP servers into the shared config, and exposes its skill
directories for playbook discovery (via `DECODE_PLAYBOOKS_DIR`). Remove reverses
all of it.

## What is NOT a plugin

Core OS operations (files, processes, services, commands) and system tools
(`nmap`, `ffuf`, …) are **not** plugins. They are native capabilities and the
discovered, shell-driven system layer respectively. Plugins are reserved for
*additional intelligence and integrations*, so the architecture never depends on
its plugin ecosystem to do basic work.

## Removed

The earlier in-tree plugin system (`decode/tools.py`, `decode/plugins/` with its
manifest/sandbox/lifecycle and bundled tool plugins) was deleted during the
universal-agent consolidation; it packaged hardcoded tools in-tree. The current
extension layer replaces it with declarative packages and external MCP providers.
