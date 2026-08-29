# Agent Instructions for Decode

These instructions apply to every coding agent working in this repository. Follow the user’s request first, then the nearest applicable `AGENTS.md`, while preserving Decode’s safety and audit invariants.

## Project Identity

Decode is a local-first, extensible cybersecurity operating system. The kernel translates explicitly authorized objectives into reviewable plans, routes capability-based work to agents and tools, enforces scope and permissions, and preserves evidence and audit history.

Decode is not a general-purpose assistant and is not an unrestricted autonomous exploitation system.

## Before Making Changes

1. Read the relevant neighboring source and tests.
2. Check [the documentation hub](docs/README.md) for the subsystem’s canonical contract.
3. Inspect `git status --short` and preserve unrelated user changes.
4. Identify whether the documented feature is **implemented**, **partial**, **planned**, or **research**.
5. Make the smallest complete change that satisfies the request.
6. Validate proportionally, then always run the repository lint and test suite.

Do not present planned systems such as the event bus, FastAPI service, PostgreSQL, Redis Streams, Qdrant, distributed workers, or Neural Schema as implemented.

## Non-Negotiable Safety Invariants

- Security work must be explicitly authorized and target-scoped.
- `ScopePolicy` is an allowlist. Empty scope denies target execution.
- Scope is checked again immediately before execution.
- Models, prompts, agents, plugins, and tool output cannot grant permission.
- `READ` may auto-allow when scope and data policy permit.
- `WRITE` requires human approval.
- `DESTRUCTIVE` defaults to deny; it requires an explicit engagement override and human approval.
- A material change to target, command, executor, credentials, privileges, or risk invalidates prior approval.
- Missing dependencies stop execution; installation is a separate approved action.
- Consequential execution fails closed when scope, permission, validation, or mandatory audit services are unavailable.
- Preserve raw output when parsing fails and label the result partial.
- Never store or print secrets in logs, audit events, registries, prompts, errors, or generated documentation.

The governance gate is the single pre-execution decision point. Do not introduce alternate execution paths around it.

## Architecture Boundaries

```text
User
  |
CLI / Rich REPL
  |
Kernel: context, planning, routing, safety
  |
Agents -> Capabilities -> Skills
  |
Execution Providers
  |
Discovered Tools
  |
Persistence / Evidence / Logs / Audit / Feedback
```

### Kernel

The kernel owns orchestration and cross-cutting policy. Domain-specific security behavior does not belong in `decode/kernel/`.

### Agents

Agents own domains and declare capabilities. They request capabilities through `CapabilityRegistry`; they do not hardcode tool names or build raw commands.

### Skills

Skills expose typed security capabilities through `SkillSpec`. They validate inputs and dependencies, execute through providers where applicable, normalize outputs, and generate all required telemetry.

### Execution providers

Providers handle platform-specific command transport. They do not decide scope or permission. Current implementations are local, Docker, WSL, SSH, and MCP.

### Persistence and memory

- SQLite is the default local operational store; an optional MongoDB backend (`MongoSessionStore`, same store contract) is selected when `MONGODB_URI` is configured. Construct stores through `create_store()`, never by hardcoding a backend.
- Raw evidence is immutable after registration and stays in the local protected evidence store even under the MongoDB backend; only hashed references are persisted to the operational store.
- Tool and model outputs are observations until verified.
- Sensitive artifacts require redacted rendering and protected handling.
- A hosted MongoDB backend moves operational data off the local machine; it is opt-in and does not change the scope, approval, or audit invariants.
- PostgreSQL, Qdrant, and distributed memory are planned, not current dependencies.

### Host control

General OS operations (files, search, processes, services, ad-hoc commands,
stateful sessions) are **first-class inbuilt capabilities**, owned by `HostAgent`
and executed through `decode/hostcontrol/`. They are never plugins.

- Every host op routes through `ExecutionCoordinator` — no alternate path.
- `FilesystemScope` (path allowlist) and `CommandPolicy` (binary allow/deny +
  argument-sensitive risk) are hard, deny-by-default filters checked immediately
  before execution. `shell_command` risk is resolved per-command before the gate.
- `PermissionMode` (plan/ask/auto) only lowers autonomy or auto-allows READ/WRITE
  in scope; it never auto-allows DESTRUCTIVE.
- Raw model-generated shell stays blocked; the governed `shell_command`
  capability (policy-checked, per-command risk-classified, scoped, audited) is the
  sanctioned replacement. It accepts a `command` string **or** a pre-split `argv`
  list and is the **primary path** for driving any installed CLI tool. A tool that
  is not installed is *reported* (`command not found`), never auto-installed.
- `list_tools` is a governed READ capability that scans `$PATH` so the agent
  discovers what is installed (there is no hardcoded tool catalog) and then drives
  it via `shell_command`.
- See [docs/HOST_CONTROL.md](docs/HOST_CONTROL.md).

### Universal agent (the interactive default)

The bare `decode ❯` prompt **is** the governed universal agent: natural-language
goals and plain questions both run through `UniversalAgent.run_tool_loop` (the same
bounded plan→call→observe loop as `/agent`). The agent discovers installed tools
(`list_tools`), drives them and scripts via governed `shell_command`, and answers
questions directly — there is no hardcoded per-tool skill and no single-skill
proposer. Extensibility is via **markdown playbooks** (see below), not Python
wrappers. Everything still routes through `ExecutionCoordinator`.

The old hardcoded capability-execution stack has been **removed**: the domain
agents (`agents/recon.py`, `web.py`, …), tool adapters (`capabilities/commands.py`),
tool catalog + discovery (`discovery/`), `env_scanner.py`, `dependency_manager.py`,
named workflows (`workflows/`), the mission runner (`runtime/mission*`), and the
`kernel` skill router are gone, along with the CLI/TUI commands that drove them
(`/assess /workflow /plan /capabilities /discover`). What remains in `agents/` is
the `Agent` base and `HostAgent`; in `capabilities/`, the host-capability specs.

## Repository Map

| Area | Source |
|---|---|
| CLI | `decode/cli.py` |
| Inline REPL | `decode/tui/app.py` |
| Kernel | `decode/kernel/` |
| Agents | `decode/agents/` |
| Host control (files, processes, services, commands, tool discovery) | `decode/hostcontrol/`, `decode/agents/host.py`, `decode/runtime/host_controller.py` |
| Tool-use agent loop (the universal agent) | `decode/runtime/agent_loop.py`, `decode/universal_agent.py` |
| Host capability specs | `decode/capabilities/models.py` |
| Skill registry (markdown playbooks) | `decode/skills/registry.py`, `decode/skills/markdown_skill.py`, `decode/skills/playbooks/` |
| Task-state / DAG primitives | `decode/planner/dag.py` (`PlanNode`, `PlanGraph`, `CompletionCriterion`) |
| Execution providers | `decode/execution/` |
| Governance | `decode/governance/` |
| Persistence | `decode/persistence/` |
| Memory | `decode/memory/` |
| Knowledge graph | `decode/knowledge/` |
| Structured logging | `decode/logging_service.py` |
| Audit | `decode/audit.py` |
| Execution feedback | `decode/feedback.py` |
| Tests | `tests/` |
| Documentation | `docs/` |

## Code Style

- Target Python 3.11 or newer.
- Add type hints to every function signature.
- Follow neighboring import, naming, error-handling, and logging patterns.
- Use relative imports inside `decode/`.
- Prefer Pydantic models at validation, serialization, and trust boundaries.
- Use `log_action()` from `decode.utils` where the existing code path expects it; it does not replace mandatory structured execution logging, audit, and feedback.
- Keep the kernel tool-agnostic and domain-neutral.
- Prefer argument vectors over shell command strings.
- Validate targets, paths, ports, ranges, enums, timeouts, and output limits.
- Use stable error categories; distinguish invalid input, policy denial, missing dependency, timeout, cancellation, execution failure, and parse failure.
- Do not add explanatory comments unless requested; express ordinary behavior through clear names and small functions.
- Match existing indentation, quotes, and line length.

## Working Tree and File Rules

- Do not create new files unless the user explicitly asks; prefer editing existing files.
- Preserve unrelated modified and untracked files.
- Do not modify generated runtime data unless it is explicitly in scope.
- Treat `.env`, `data/*.db*`, `logs/`, `audit/`, `feedback/`, evidence, and model indexes as potentially sensitive user data.
- Never commit, stage, push, create a branch, or open a pull request unless explicitly asked.
- Never use destructive Git commands to discard user work.

## Capability-First Development

Planning and agents operate on capabilities such as `port_scan`, not binaries such as `nmap`.

When adding or changing tool support:

1. Define or reuse a stable capability.
2. Add discovery metadata with a safe version probe.
3. Declare supported providers, platforms, versions, privileges, and dependencies.
4. Build arguments from typed normalized parameters.
5. Classify baseline and argument-dependent risk.
6. Preserve raw output and normalize through a version-aware parser.
7. Add fixtures for success, partial, malformed, timeout, and unsupported-version output.
8. Report capability coverage rather than package count.

Never execute a skill whose required dependency is unavailable. Return actionable guidance:

```text
Required dependency missing: nuclei
Install? sudo apt install nuclei
```

Installation must not happen automatically.

## Adding or Updating a Skill

**Do not add Python tool-wrapper skills.** The hardcoded per-tool skills were
removed; the agent runs any installed tool through the governed `shell_command`
capability instead. To add a repeatable capability, write a **markdown playbook**
(below). `Skill`/`SkillSpec`/`SkillRegistry` still exist only to host playbooks and
must not be used to hardcode a tool's argv or parser.

### Markdown playbook skills (`SKILL.md`)

A capability is authored as a **markdown playbook**: a `.md` file with YAML
frontmatter (`name`, `description`, `risk`, `category`, `tags`, `inputs`) and a
body of instructions
(`decode/skills/markdown_skill.py`). Invoking a playbook executes nothing
itself — it returns its instructions as an observation, and the agent carries them
out through the governed `shell_command` capability (each command separately gated).
This lets new tool workflows be added as prose without a hardcoded adapter.

- Drop `.md` files in `decode/skills/playbooks/`, or point
  `DECODE_PLAYBOOKS_DIR` (`os.pathsep`-separated) at your own directories.
- Malformed files are skipped, never fatal to registry load.
- Playbook risk defaults to `READ` (retrieving guidance); the commands it triggers
  are risk-classified individually at execution time.

## Adding or Updating an Agent

- Inherit from `Agent`.
- Use a stable `domain`.
- Declare a precise, preferably disjoint capability set.
- Route tool-backed work through `CapabilityRegistry`.
- Use `execute_internal()` only for genuinely internal capabilities.
- Respect the task’s scope, memory, tool, executor, model, timeout, retry, and approval bounds.
- Return `AgentResult` with an accurate success state, summary, output, and stable error.
- Do not retry a denial or consequential action automatically.
- Add tests for routing, missing capabilities, denied approval, failures, and partial results.

## Extension Rules

There is **no in-tree plugin system**. `decode/tools.py` (`PluginManager`) and
`decode/plugins/` (manifest, sandbox, lifecycle, and bundled tool plugins) were
removed. Do not reintroduce a tool catalog, an in-process plugin loader, or
per-tool Python wrappers.

Extend Decode through:

- **Markdown playbooks** (`SKILL.md`, above) for repeatable procedures.
- **Native capabilities** in `decode/hostcontrol/operations.py`, wired through
  `HostAgent`, for genuinely new OS primitives.

*Plugins* are reserved for optional, isolated connectors to **external** systems
(issue trackers, cloud providers, hosted scanners, MCP servers) — never in-tree
security tools and never core OS operations. That surface is planned, not built;
any future design must pass typed I/O through `ExecutionCoordinator` under
isolation, with the same audit/log/feedback telemetry as every other governed
execution. See [docs/PLUGIN_MANIFEST.md](docs/PLUGIN_MANIFEST.md).

## Mandatory Execution Telemetry

Every skill execution, including failures and denials where applicable, must produce:

1. A structured execution record through `LoggingService.log_execution()`.
2. An audit record through `AuditLayer.record_execution()` or the appropriate denial event.
3. Execution feedback through `FeedbackStore.record_execution()`.

### Structured log

```json
{
  "timestamp": "ISO8601",
  "tool": "skill_name",
  "command": "redacted command",
  "status": "success",
  "duration": 12.4,
  "output_file": "logs/skill_name/result.json"
}
```

### Audit event

```json
{
  "event": "tool_execution",
  "tool": "skill_name",
  "target": "authorized-target",
  "risk": "WRITE",
  "approved": true
}
```

### Execution feedback

Record skill, success, execution time, dependency state, stable error, and non-sensitive metadata.

Redact secrets and tokens. Record denial reasons without copying sensitive payloads.

## Startup Lifecycle

```text
Bootstrap Engine
       |
Environment Scan
       |
Dependency Validation
       |
Skill (markdown playbook) Loading
       |
Provider Initialization
       |
Host Capability Registration
       |
Agent Ready
```

Startup should report degraded optional capabilities. Missing safety, governance, or mandatory audit prerequisites must prevent execution.

## TUI Architecture

The TUI in `decode/tui/` is a Rich + prompt_toolkit inline REPL, not a full-screen Textual application.

```text
AgentREPL
  +-- Rich Console
  +-- PromptSession with history
  +-- Synchronous run loop
        +-- command dispatch
        +-- asyncio.run() for async agent calls
```

- `decode/cli.py` calls `AgentREPL.run()`.
- Commands execute sequentially.
- There are no screens, widgets, custom messages, or implemented event bus.
- Preserve this architecture unless the user explicitly requests a TUI redesign.

Supported REPL commands include:

```text
/start
/chain
/session
/findings
/evidence
/plugins
/resume <id>
/clear
/exit
```

## Testing

run commands in wsl if testing in windows

Tests live in `tests/` and use pytest.

Required after every change:

```text
ruff check .
python -m pytest tests/
```

`pytest tests/` is acceptable when the active launcher includes the repository root on `sys.path`.

Add tests for:

- Normal behavior.
- Invalid and boundary inputs.
- Scope and permission denials.
- Missing dependencies.
- Timeouts, cancellation, and retries.
- Parser failures and partial output.
- Secret redaction.
- Mandatory log, audit, and feedback records.

Live model APIs and security tools must not be required by the unit suite. Use fixtures, fakes, or explicitly opt-in integration tests.

## Documentation

- Start at `docs/README.md`.
- Preserve the distinction between **implemented**, **partial**, **planned**, and **research**.
- Update the relevant canonical specification when a contract changes.
- Add an ADR under `docs/adr/` for durable architecture decisions only when the user authorizes a new file.
- Use legal synthetic, non-routable, or explicitly controlled targets in examples.
- Do not duplicate the root security, contribution, license, or release-roadmap policies.
- Verify relative Markdown links after documentation changes.

## Handoff

Keep user-facing responses concise. State:

- What changed.
- Important safety or compatibility implications.
- Validation performed and results.
- Any remaining limitation or blocked check.

Do not claim success when required validation did not run or failed.
