# MCP and Local Tool Service

**Status:** Current MCP/HTTP foundations; v2 capability envelopes Target

De-code may expose governed capabilities and consume external MCP. MCP is
transport/provider, not authority. Calls still pass schema, scope, risk,
approval, coordinator, evidence, audit, usage.

```bash
decode mcp start
decode mcp start --port 9000
decode mcp start --transport stdio
decode mcp status
decode mcp stop
decode mcp config
decode mcp add NAME -- COMMAND...
decode mcp add NAME --transport http --url URL
decode mcp list
decode mcp disable NAME
decode mcp remove NAME
```

Current package metadata defines optional dependencies. HTTP stays localhost by
default; remote exposure needs auth/TLS.

Registration, start/connect, discovery, registration, authorization, invocation,
and evidence are separate. Servers get no ambient access. Validate schemas and
declared effects; do not trust risk labels.

Expose only enabled schemas. Headless services cannot self-approve. Approval and
project isolation cross transport.

Target lifecycle: validate config/source; start/connect isolated; discover
versioned schema; map envelope; apply policy/data handling; invoke coordinator;
record evidence/audit/usage; health/revoke/stop.

Use least privilege, egress/filesystem/credential limits, size/time/rate,
injection defenses, and retention. Remote/cloud MCP is Deferred.
