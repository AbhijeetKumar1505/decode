# De-code — Pre-AWS Engineering Roadmap

Status baseline: commit `2009167` (src-layout, `src/decode/`, v1.0.0).

This roadmap reconciles the proposed "build the core before AWS" plan with what the
codebase already implements. The short version: **De-code is substantially further
along than a from-scratch checklist assumes.** A mature governance/execution core, a
full slash-command REPL, a policy-based model router, session persistence, and
observability all exist today. The value of this document is to name the *few* gaps
that actually gate an AWS deployment and to order the work so we do not re-implement
working code.

## Foundation status

| # | Foundation | Status | Evidence / gap |
|---|---|---|---|
| 1 | Core agent runtime | **Done** | `runtime/agent_loop.py` (`ToolUseLoop`), `runtime/coordinator.py`, `universal_agent.py`, `schema/task_state.py` |
| 2 | Auth & authorization | **Missing** | No user accounts / API keys / tokens / roles; single local user |
| 3 | Rate limits & budgets | **Partial (metadata only)** | `RateLimit` (TPM/RPS) + `cost_budget_per_mtok` are *routing filters* in `models/registry.py` / `models/routing.py`; no enforced per-user quota or budget ceiling |
| 4 | Model catalogue | **Partial** | Rich `ModelSpec` registry (~22 models); only 3 provider adapters (OpenRouter/OpenAI/Anthropic) — no Bedrock, no Mistral in code |
| 5 | Model orchestration | **Done (routing) / Partial (classify)** | `ModelRouter` (hard filters + ranking + fallback) + role→task_class gateway; no prompt task-classifier |
| 6 | Memory & knowledge base | **Partial** | session/project scopes, knowledge graph, FAISS self-learning (not wired to `MemoryManager`); no user/global scope, no expiry, no versioning/edit |
| 7 | Transcript & run logging | **Partial** | audit JSONL + per-tool logging + feedback + `ReplayRecord`; correlation is per-tool `request_id`, no session-level run/trace id, no cost metering |
| 8 | Sandbox & policy engine | **Done** | `governance/gate.py` (ALLOW/NEEDS_APPROVAL/DENY), approval TTL, `execution/*` providers guarded by `_ACTIVE_EXECUTION_CONTEXT` |
| 9 | Evaluation & regression suite | **Partial** | offline scorers (`evaluation.py`, `data/evaluations/*.json`), `Verifier`/`ModelVerifier`, ~30 test files; gaps: replay/observability untested, no routing eval harness |
| 10 | CLI packaging | **Partial** | Poetry wheel + `decode` console script + Dockerfile + CI; no npm, no install.sh, no PowerShell, no GitHub Releases, no self-update |
| 11 | API contract & deployment | **Missing** | No FastAPI / HTTP / ASGI / `/health` anywhere; pure in-process CLI + TUI |
| 12 | Usage metering & billing | **Missing** | tokens tracked on the provider; no usage→cost accumulation, no attribution, no plans/alerts |

**3 done, 6 partial, 3 missing.** The fully-missing items (auth, HTTP API, usage/billing)
plus the MCP-server gap are what actually gate AWS.

## Reconciliation notes

- **Architecture** — Already a modular monolith with interface seams (`ExecutionProvider`,
  `LLMProvider`, `Capability`, `SessionStore`). Security-boundaries-by-default is
  implemented in `governance/gate.py`. "Everything measurable" is ~70% there — tokens,
  latency, and tool-calls are captured; **cost is not**.
- **MoE vs. router** — What exists is a multi-model *router* keyed on `task_class`, not a
  learned MoE, which is the right starting point. Single-model per role by default;
  routing is opt-in (`DECODE_MODEL_ROUTING=1`). "coding/reasoning/fast/review" map to
  existing task classes (`code`/`planning`/`analysis`); "fast" is a `latency_class`. The
  real missing piece is an automatic *prompt classifier* to pick the class.
- **Memory** — session + project scopes exist (no user/global); provenance on knowledge
  nodes; keyword retrieval with optional semantic (FAISS present but unwired to
  `MemoryManager`); delete exists, edit/version and expiry/confidence do not. Sensitive
  values are flagged and redacted on export but **stored plaintext in SQLite**.
- **Transcript logging** — Correlation is per-tool-call (`request_id` + `approval_digest`),
  not per-agent-run. There is no session-level `run_id`/`trace_id` spanning a whole run,
  and no per-run cost estimate. `ReplayRecord` is the closest schema but is a value object.
- **MCP server** — Largest single gap. De-code is an MCP *client only, stdio only*
  (`extensions/mcp_client.py` raises `NotImplementedError` for http/sse). `hostcontrol/mcp.py`
  already emits MCP-shaped descriptors of governed capabilities, but nothing serves them.
  No FastAPI, port, `/health`, or `decode mcp start/stop/status`.
- **CLI / slash commands** — Most UX already exists: Rich rendering, spinners, step-event
  streaming, interactive approval, autocomplete, shortcuts, grouped `/help`. Missing:
  `/status`, non-interactive `--json` output, token-by-token streaming, and the session/mcp
  commands below.
- **Sessions** — `SessionStore` (SQLite + Mongo) + resume/`--continue`/`/resume` work.
  Gaps: auto-init only fires on an IP in the message (not unconditionally on first prompt);
  IDs are bare `uuid4()` (not `dc_YYYYMMDD_xxxx`); no core `SessionManager` (lifecycle is in
  the REPL); no `/sessions` `/continue` `/checkpoint`; `TaskState` checkpointing is not
  wired to the session id.

## Build sequence

Ordered by *unblocks-the-most* and *smallest coherent slice*. Each phase is independently
shippable and reuses existing seams.

**Phase 0 — Correctness & hygiene** *(done in this pass)*
- Fixed the broken import at `app/cli.py` (`.universal_agent` → `..universal_agent`).
- Corrected stale references: this `ROADMAP.md`/adapter list and the `/model` help example.
- Added `decode version` and the `/version` slash command (wires `__version__`).

**Phase 1 — MCP server + FastAPI localhost** (biggest gap) — *complete*
- Done: `src/decode/mcp/` package — a transport-independent core (`config.py`, `server.py`)
  serving the *existing* governed capabilities via `hostcontrol/mcp.py::host_capability_tools()`,
  routing every call through `ExecutionCoordinator` (governance, approval, audit, evidence all
  apply). `transport.py` provides a lazy FastAPI app (`/health`, `GET /tools`, `POST /tools/{name}`)
  behind the optional `decode[server]` extra, with run-state bookkeeping.
- Done: native **MCP-protocol stdio binding** (`src/decode/mcp/stdio.py`) via the `mcp` SDK
  (`decode[mcp]` extra) — `decode mcp start --transport stdio` serves the governed tools so
  standard MCP clients (Claude Desktop, IDEs, other agents) discover and invoke them directly.
  A shorthand→JSON-Schema normalizer (`schema.py`) makes the tool schemas pass MCP metaschema
  validation; verified end-to-end with a real MCP client (initialize → list_tools → call_tool).
- Done: `mcp` Typer group extended with `start [--transport http|stdio] --port 8765 / stop /
  status / config` (local bind by default; governance `--mode` and `--read-root`/`--write-root`
  scope flags). `tests/test_mcp_server.py` covers discovery, governance modes, approval gating,
  the HTTP layer, the schema normalizer, and the stdio server build.
- Done: native MCP **streamable-HTTP** server transport — the FastAPI app mounts a
  `StreamableHTTPSessionManager` at `/mcp` (when `decode[mcp]` is installed), so `decode mcp
  start` serves the REST convenience API *and* native MCP over one port for remote clients.
- Done: **client-side** http/sse transport in `extensions/mcp_client.py` — De-code can now also
  *consume* external MCP servers over streamable-HTTP and SSE (`decode mcp add … --transport
  http --url …`), not just stdio. Both server and client verified end-to-end with real MCP
  sessions (initialize → list_tools → call_tool).

**Phase 2 — Session core + command/UX parity** — *complete*
- Done: core `SessionManager` (`persistence/manager.py`) wrapping `SessionStore` — create /
  resolve / list / latest / status / close / reactivate + transcript save/load; the REPL now
  instantiates it (`self._sessions`) and the new commands use it.
- Done: **`dc_YYYYMMDD_xxxx`** session ids via `_new_session_id()` in both the SQLite and Mongo
  stores (other entity ids stay UUIDs).
- Done: **unconditional auto-init** — a session is created on the first task (no `/start`),
  seeded with the task as its goal and any detected target as scope (`_ensure_session`).
- Done: slash commands **`/sessions` `/status` `/continue` `/reset`** (help + autocomplete +
  dispatch), alongside the existing `/mcp start|stop|status`.
- Done: `/checkpoint` persists the transcript + a `TaskState` snapshot keyed to the live
  session id via `TaskStateStore`; `run_tool_loop` now threads the session id and exposes the
  live `TaskState`. Added the missing `save_task_state`/`load_task_state` to the **Mongo** store
  (SQLite had them) so checkpointing works on either backend.
- Done: `--json` / non-interactive output — `decode providers|tools|mcp status --json` and a new
  `decode sessions [--json]` command (non-interactive equivalent of `/sessions`).
- Done: migrated the legacy REPL `_resume_session`/`_save_session`/`_resume_latest` onto
  `SessionManager` (transcript + lifecycle in the core).
- Also fixed a batch of import bugs the src-layout move left in `app/cli.py` (sibling-package
  imports `from .execution`/`.hostcontrol`/`.knowledge`/`.extensions` → `..`), which had broken
  `decode providers/tools/knowledge/doctor/mcp` as non-interactive subcommands.

**Phase 3 — Providers, classifier & usage metering**
- `BedrockProvider` (and optionally `MistralProvider`) implementing `LLMProvider`; register in
  `create_provider` + `_KNOWN_PROVIDERS`; add registry `ModelSpec`s.
- Lightweight prompt task-classifier feeding `RoutingRequest.task_class`.
- Usage→cost metering (`session_tokens` × `ModelCost`) and a session-level `run_id`/trace
  joining model-selection + tool-calls into one persisted record.

**Phase 4 — Memory lifecycle & eval hardening**
- User/global memory scope; artifact edit/version + optional expiry/confidence; wire
  `SelfLearningMemory` (FAISS) into `HybridRetriever` as the semantic backend.
- Routing/tool-correctness regression harness; tests for `observability/replay.py` and audit sinks.

**Phase 5 — Release engineering**
- npm wrapper, checksummed `install.sh`, PowerShell installer, winget manifest; GitHub Releases
  workflow with checksums; `decode update`/`uninstall` (preserve `~/.decode` by default); semver channels.

**Phase 6 — Auth, quotas, API contract (the AWS on-ramp)**
- User accounts / API keys / tokens / roles / project access.
- Enforce rate limits + token/cost budgets per user (turn `RateLimit`/budget metadata into runtime enforcement).
- Freeze a stable HTTP API contract + Docker image for a minimal AWS deploy; transcripts to S3/DB
  using the provider-neutral schema from Phase 3.

## Explicitly deferred

Kubernetes, true MoE training, a custom vector database (the FAISS file index is sufficient),
multi-region, subscription billing, and fully-autonomous pentesting expansion — none of these
are built before the AWS on-ramp above.
