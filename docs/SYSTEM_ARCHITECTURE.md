# System Architecture

## System overview

Decode is a synchronous CLI/REPL application that drives a single **governed
universal agent loop**. It separates four concerns: user interaction (CLI/REPL),
orchestration (the tool-use loop), governed execution (the coordinator + host
capabilities), and persistence (operational store, evidence, knowledge, memory).
Model and executor access are pluggable. There is no multi-agent roster, tool
registry, or event bus — those earlier designs were removed.

## Maturity legend

- **Implemented** — working source exists in this repository and is tested.
- **Partial** — a working foundation exists but does not yet satisfy the full target.
- **Planned** — direction only.

## Architecture layers

```text
User / Operator  (natural-language goal or question)
        |
        v
Frontends (over one runtime, via a typed event bus)   Implemented
  inline REPL (decode/tui/app.py, default `decode`)
  Textual console (decode/tui/console.py, `decode tui`)
  events: decode/events/ · state: decode/tui/state.py
        |
        v
Universal agent loop                            Implemented
  UniversalAgent.run_tool_loop + ToolUseLoop
  (plan -> call one tool -> observe -> iterate)
        |
        v  every tool call
ExecutionCoordinator                            Implemented
  filesystem scope · target scope · per-command
  risk · permission mode · bound approval ·
  audit · hashed evidence   (fail-closed)
        |
        v
Governed capabilities                           Implemented
  HostAgent / hostcontrol:
   list_tools · shell_command · host_session ·
   file read/write/edit/search · process · service
        |
        +-- shell_command --> any installed CLI + your scripts
        |                     (+ SKILL.md markdown playbooks)
        |
        v
Execution providers                             Implemented
  Local | Docker | WSL | SSH | MCP
        |
        v
Persistence, evidence, logs, audit, knowledge   Implemented
  SQLite (optional MongoDB), evidence store,
  knowledge graph, project/session memory
```

## De-code subsystems

The target architecture is ten subsystems with a strict separation between what
the **model** decides (reasoning, planning, tool selection, interpretation) and
what the **runtime** enforces (permissions, scope, execution, state,
verification). The table maps each subsystem to its source and honest status.

| # | Subsystem | Source | Status |
|---|---|---|---|
| 01 | Model Gateway | `decode/models/{registry,routing,gateway}.py`, `decode/kernel/provider.py` | **Implemented** — `ModelGateway` maps roles (planner/worker/reviewer/coder) to a provider via the policy-aware router. Single-model by default; per-role overrides (`DECODE_<ROLE>_MODEL`) and opt-in routing (`DECODE_MODEL_ROUTING=1`) enable multi-model. |
| 02 | Prompt Engine | `decode/prompting/composer.py` | **Implemented** — the loop's system prompt is composed from fragments: BASE + MODE + CAPABILITIES + POLICY + task-state note + optional project rules. (`decode/prompt_engine.py` remains for domain/template prompts.) |
| 03 | Agent Runtime | `decode/runtime/agent_loop.py`, `decode/universal_agent.py` | **Implemented** — bounded reason→resolve→call→observe→verify→iterate loop. |
| 04 | Task State (Neural Schema) | `decode/schema/{task_state,store}.py` (reusing `planner/dag.py`) | **Implemented** — a live `TaskState` (objective, mode, scope, hypotheses, plan, actions, observations, findings, questions, completion conditions) that the loop reads and writes each turn; persisted via `SessionStore`. |
| 05 | Capability Registry | `decode/capabilities/{models,coding,resolver}.py`, `decode/runtime/host_controller.py` | **Implemented** — typed host capabilities + typed coding capabilities (git/test/build/patch, translated to governed `shell_command`); a per-turn resolver scopes the surface by mode. Non-coding external tools stay discovered (`list_tools`) and shell-driven. |
| 06 | Policy Engine | `decode/governance/{gate,scope}.py`, `decode/hostcontrol/policy.py` | **Implemented** — scope + per-command risk + permission mode + bound approval, all audited and fail-closed. |
| 07 | Execution Runtime | `decode/execution/*`, `decode/hostcontrol/{session,operations}.py` | **Implemented** — Local / Docker / WSL / SSH / MCP behind one interface; a persistent governed session (`session_open/exec/close`, subsystem 12) keeps cwd/env across turns, argv-governed. |
| 08 | Observation Engine | `_observe()` in `universal_agent.py`, `capabilities/coding.py` parsing, `redact_sensitive` | **Implemented** — `{success, summary, data, evidence}` with redaction; shell results carry exit code/stdout/stderr/duration, and coding results add parsed signals (test pass/fail, files changed). |
| 09 | Artifact / Memory Store | `decode/persistence/evidence.py`, `decode/schema/task_state.py` (Artifact), `decode/memory/*`, `decode/knowledge/*` | **Implemented** — immutable hashed evidence, project/session memory, knowledge graph, audit, feedback; each step's evidence is linked to the task state as an `Artifact`. |
| 10 | Verification Engine | `decode/verification/verifier.py` | **Implemented** — a rule-based verifier gates a "done" message on completion conditions and drives bounded replan (inert unless declared); an opt-in reviewer-model backend (`ModelVerifier`, `DECODE_MODEL_REVIEW=1`) adds a semantic review on top. |

The full task-state spine (#04→#10) and its enhancements are in place: the
persistent governed session (#12), task-state↔evidence artifact linking (#09),
and the reviewer-model verifier backend (#10). #06, #07, and the core of #09
already matched the target and were not rewritten. See
[ROADMAP.md](../ROADMAP.md) for sequencing.

## The agent loop

`UniversalAgent.run_tool_loop` (`decode/universal_agent.py`) builds the tool
surface — the host capabilities plus any markdown playbooks — and hands it to
`ToolUseLoop` (`decode/runtime/agent_loop.py`). The loop:

1. Shows the model the available tools and the goal.
2. Asks for a single JSON decision: call one tool, or return a final message.
3. Executes the call through the governed `invoke` path (host capabilities via
   `HostController`; markdown playbooks via `execute_registered_skill`).
4. Feeds the observation back and repeats until the goal is met or the step
   budget is exhausted.

The bare `decode ❯` prompt and the `/agent` command are the same path. A plain
question is answered by the loop returning a message without calling any tool.

## Governed execution

Every tool call routes through `ExecutionCoordinator`
(`decode/runtime/coordinator.py`). `HostController`
(`decode/runtime/host_controller.py`) classifies each `shell_command` /
`host_session` per-command **before** the gate, so a WRITE command needs approval
and a DESTRUCTIVE one hits the destructive control regardless of the capability's
baseline risk. Policy comes from two deny-by-default allowlists:

- `FilesystemScope` — separate read/write path roots; resolves `..` and symlinks
  before the check.
- `CommandPolicy` — binary allow/deny plus argument-sensitive risk classification.

`PermissionMode` (`plan` | `ask` | `auto`) layers autonomy on top of the risk
gate and can never auto-allow DESTRUCTIVE. See [EXECUTION_PIPELINE.md](EXECUTION_PIPELINE.md)
and [SECURITY_MODEL.md](SECURITY_MODEL.md).

## Host capabilities

Owned by `HostAgent` (`decode/agents/host.py`), executed through
`decode/hostcontrol/operations.py`. All are first-class `kind="internal"`
capabilities in `decode/capabilities/models.py` — there is no external-tool
capability taxonomy.

| Capability | Risk | Notes |
|---|---|---|
| `list_tools` | READ | Scan `$PATH` for installed tools (discovery) |
| `file_read` / `file_list` / `file_search` | READ | Within the filesystem scope |
| `file_write` / `file_edit` / `file_fetch` | WRITE | Within the writable scope |
| `process_list` / `service_status` | READ | Host inspection |
| `process_kill` / `service_control` | DESTRUCTIVE | Gated |
| `shell_command` | WRITE (per-command classified) | Run any installed CLI or script as an argument vector |
| `host_session` | WRITE (per-command classified) | Stateful command sequence (one batch) |
| `session_open` / `session_close` | READ | Open/close a persistent session that keeps cwd/env across turns |
| `session_exec` | WRITE (per-command classified) | Run one command in the persistent session |

## Extensibility

Three tool sources sit behind one source-tagged capability registry
(`decode/capabilities/registry.py`); the agent selects capabilities without
caring where they came from, and every call still routes through the coordinator.

- **Native capabilities** (`decode/hostcontrol/`, `decode/agents/host.py`): the
  first-class OS primitives listed above. New primitives are added here and wired
  through `HostAgent` — never as plugins.
- **System tools** (`list_tools` + `shell_command`): discovered on `$PATH` and
  shell-driven. Deliberately **not** registered per-binary, so the architecture
  never depends on cataloguing every tool.
- **Markdown playbooks** (`decode/skills/markdown_skill.py`, `playbooks/`, or
  `DECODE_PLAYBOOKS_DIR`): a `SKILL.md` surfaced as a tool; invoking it returns
  instructions the agent carries out via governed `shell_command`. No Python.
- **MCP servers** (`decode/extensions/mcp_manager.py`, `decode mcp …`): external
  tool providers, discovered via `tools/list`, started lazily, namespaced per
  server (`mongodb.find`), with a **declared** risk (MCP payloads are opaque, not
  argv-classifiable). Executed through `MCPExecutor` under the coordinator.
- **Plugin packages** (`decode/extensions/plugin_manager.py`, `decode plugin …`):
  declarative bundles (manifest + markdown skills + MCP configs + docs) — never
  in-process code, so no arbitrary-code-execution risk. Install verifies the
  manifest and fails closed. See [PLUGIN_MANIFEST.md](PLUGIN_MANIFEST.md).

Configuration for the external providers is scoped (project > user > system;
`~/.decode/`, `./.decode/`, `/etc/decode/`). The removed in-tree plugin loader
(`decode/tools.py`, `decode/plugins/`) is gone; these declarative packages and
external MCP providers replace it.

## Persistence and memory

Durable storage uses SQLite by default (optional MongoDB via `MONGODB_URI`,
selected by `create_store()`): sessions, targets, findings, evidence, projects,
and artifacts. A knowledge graph supplements this with security entities and the
capability → MITRE ATT&CK mapping (`decode/knowledge/`). See
[MEMORY_ARCHITECTURE.md](MEMORY_ARCHITECTURE.md) and
[DATABASE_SCHEMA.md](DATABASE_SCHEMA.md).

## Deployment models

| Model | Description | Status |
|---|---|---|
| Local workstation | CLI, loop, SQLite, and local tools in one process | Implemented |
| Windows + WSL | Windows control plane with Linux tools through WSL | Implemented |
| Containerized execution | Local control plane with Docker-isolated commands | Implemented |
| Remote SSH executor | Commands dispatched to an explicitly configured host | Implemented |
| MCP executor | Calls a configured MCP client | Implemented |

## Architectural invariants

- The model cannot grant itself permission; every tool call passes the coordinator.
- Per-command risk is resolved before the gate; DESTRUCTIVE is never auto-allowed.
- Scope (filesystem and target) is evaluated at execution time, not only at planning.
- A missing tool is reported (`command not found`), never auto-installed.
- Raw evidence is immutable after registration; telemetry carries references, not raw output.
- Fail closed when scope, permission, audit, or evidence capture is unavailable.
