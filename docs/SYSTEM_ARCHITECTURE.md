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
CLI and REPL                                    Implemented
  decode/cli.py, decode/tui/app.py
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
| 07 | Execution Runtime | `decode/execution/*`, `decode/hostcontrol/{session,operations}.py` | **Implemented** — Local / Docker / WSL / SSH / MCP behind one interface. |
| 08 | Observation Engine | `_observe()` in `universal_agent.py`, `capabilities/coding.py` parsing, `redact_sensitive` | **Implemented** — `{success, summary, data}` with redaction; shell results carry exit code/stdout/stderr/duration, and coding results add parsed signals (test pass/fail, files changed). |
| 09 | Artifact / Memory Store | `decode/persistence/evidence.py`, `decode/memory/*`, `decode/knowledge/*`, `decode/audit.py`, `decode/feedback.py` | **Implemented** — immutable hashed evidence, project/session memory, knowledge graph, audit, feedback. Task-state↔evidence linking is a planned enhancement. |
| 10 | Verification Engine | `decode/verification/verifier.py` | **Implemented** — a rule-based verifier gates a "done" message on the task's completion conditions and drives bounded replan; inert unless conditions are declared. |

The task-state spine (#04→#10) is in place. Remaining enhancements: a persistent
governed session across turns (#12), task-state↔evidence artifact linking (#09),
and an optional reviewer-model verifier backend for #10. #06, #07, and the core
of #09 already matched the target and were not rewritten. See
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
| `host_session` | WRITE (per-command classified) | Stateful command sequence |

## Extensibility

- **Native capabilities** (`decode/hostcontrol/`, `decode/agents/host.py`): the
  first-class OS primitives listed above. New primitives are added here and wired
  through `HostAgent` — never as plugins.
- **Markdown playbooks** (`decode/skills/markdown_skill.py`,
  `decode/skills/playbooks/`, or `DECODE_PLAYBOOKS_DIR`): a `SKILL.md` file
  is surfaced as a tool; invoking it returns its instructions, which the agent
  carries out via governed `shell_command`. No Python wrapper required. This is
  the sanctioned way to add repeatable procedures today.
- **External-integration plugins** (planned): optional connectors to *external*
  systems (issue trackers, cloud providers, scanners as a service, MCP servers).
  Per the De-code plan these are always optional, never in-tree security tools.
  The earlier in-process plugin loader and the manifest/sandbox/lifecycle code
  (`decode/tools.py`, `decode/plugins/`) have been **removed**; see
  [PLUGIN_MANIFEST.md](PLUGIN_MANIFEST.md) for what a future plugin surface must
  satisfy.

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
