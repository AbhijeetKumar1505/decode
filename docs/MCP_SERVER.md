# MCP server and HTTP endpoint

Decode can expose its **governed host capabilities** to MCP-compatible clients
(Claude Desktop, IDEs, other agents) and to plain HTTP clients. It can also
**consume** external MCP servers as tools.

The server is a transport, not a new execution path: every tool call still runs
through `ExecutionCoordinator`, so scope, permission mode, approval, audit, and
protected evidence apply exactly as they do in the REPL. The model/tool caller
can propose an action; it cannot grant itself permission.

## Optional dependencies

The core is dependency-light; transports live behind optional extras:

```bash
pip install -e '.[server]'   # FastAPI + uvicorn — the localhost HTTP transport
pip install -e '.[mcp]'      # the MCP SDK — native MCP over stdio and HTTP
pip install -e '.[server,mcp]'  # both
```

Without an extra, the matching transport degrades to a clear message rather than
crashing. Poetry users: `poetry install -E server -E mcp`.

## Running the server

```bash
decode mcp start                       # HTTP on http://127.0.0.1:8765, mode=ask
decode mcp start --port 9000           # custom port
decode mcp start --transport stdio     # native MCP over stdio
decode mcp start --mode auto \
  --read-root /home/lab --write-root /home/lab/out
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--transport` | `http` | `http` (localhost REST + native MCP at `/mcp`) or `stdio` (native MCP over stdio) |
| `--port` | `8765` | Port for the HTTP transport |
| `--host` | `127.0.0.1` | Bind address; local-only by default |
| `--mode` | `ask` | Governance mode: `plan`, `ask`, or `auto` |
| `--read-root` | cwd | Filesystem read-scope root (repeatable) |
| `--write-root` | — | Filesystem write-scope root (repeatable) |

Manage a running server:

```bash
decode mcp status   # recorded endpoint + a /health ping
decode mcp stop     # stop the server recorded by `start`
decode mcp config   # default binding + the governed tools that would be exposed
```

### Governance modes

The `--mode` maps to the same permission model as the REPL:

- `plan` — every tool is denied (inspection only).
- `ask` — READ tools run; WRITE/DESTRUCTIVE need approval, so on a headless
  server (no interactive approver) they are denied. Safe default.
- `auto` — WRITE tools run without prompting; DESTRUCTIVE is still gated. Powerful
  — use only on a local, trusted endpoint.

## Transports

### HTTP REST (`decode[server]`)

A convenience JSON API for scripts and quick checks:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness, mode, tool count, and the MCP endpoint (if mounted) |
| `GET` | `/tools` | List the exposed governed tools with JSON-Schema inputs |
| `POST` | `/tools/{name}` | Invoke one tool |

The POST body accepts either `{"arguments": {…}}` or a bare arguments object:

```bash
curl -s http://127.0.0.1:8765/health
curl -s http://127.0.0.1:8765/tools
curl -s -X POST http://127.0.0.1:8765/tools/file_read \
  -H 'content-type: application/json' \
  -d '{"arguments": {"path": "/home/lab/notes.txt"}}'
```

### Native MCP over HTTP (`decode[mcp]`)

When the MCP SDK is installed, the HTTP server also mounts a native MCP
**streamable-HTTP** endpoint at `/mcp`, so standard MCP clients connect to one
URL: `http://127.0.0.1:8765/mcp`. `GET /health` reports this under
`mcp_endpoint`.

### Native MCP over stdio (`decode[mcp]`)

For MCP clients that launch a tool server as a subprocess:

```bash
decode mcp start --transport stdio
```

The protocol speaks on stdout; Decode prints only its startup note to stderr so
the stream stays clean.

## Exposed tools

The server exposes the governed host capabilities:

`file_read`, `file_list`, `file_search`, `file_write`, `file_edit`,
`file_fetch`, `list_tools`, `process_list`, `process_kill`, `service_status`,
`service_control`, `shell_command`, `host_session`, `session_open`,
`session_exec`, `session_close`.

Each carries a baseline risk and a JSON-Schema input; `shell_command` and the
session commands are risk-classified per command before the gate. Restrict the
exposed set at the server core with `enabled_tools` when embedding it
programmatically.

## Consuming external MCP servers

Decode can also use other MCP servers as tools. Register them and they flow into
the agent's governed capability registry:

```bash
# stdio subprocess server
decode mcp add mongodb -- npx -y mongodb-mcp-server

# modern streamable-HTTP server
decode mcp add example --transport http --url https://mcp.example.com/mcp

# legacy Server-Sent-Events server
decode mcp add legacy --transport sse --url https://mcp.example.com/sse

decode mcp list
decode mcp disable example
decode mcp remove example
```

Each server declares a `risk`; MCP tool calls are gated by that declared risk
since an argument vector is not available to classify.

## Security notes

- The HTTP server binds to `127.0.0.1` by default and has **no authentication**.
  Do not bind a non-local address or expose it without an authenticating proxy.
- Governance is unchanged: a call that would be denied in the REPL is denied over
  the server too.
- Programmatic embedding uses `decode.mcp.DecodeMCPServer` / `MCPServerConfig`;
  the transports live in `decode.mcp.transport` (HTTP) and `decode.mcp.stdio`
  (native MCP).
