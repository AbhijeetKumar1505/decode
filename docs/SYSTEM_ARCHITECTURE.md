# De-code v2 System Architecture

**Status:** Target mapped onto the current Python baseline

## System view

```text
CLI / API / Desktop
        |
Core Brain ---------- UTOS
        |               |
Workflow Registry -> DAG Scheduler + Runtime FSM
        |               |
Active Brain ------ Context / Working Memory
        |
Execution Kernel
  capability -> policy/scope/risk -> approval -> environment
        |
Verification / Evidence / Findings
        |
SQLite Events / State / Memory / Usage / Audit
```

## Responsibilities

Core owns intent, workflow, criteria, DAG, priority, budget, delegation, material
replan, escalation, and stop. It cannot execute. Active owns one authorized node:
context, tool proposals, observation, working memory, bounded recovery, local
verification, and escalation. See [BRAIN_ARCHITECTURE.md](BRAIN_ARCHITECTURE.md).

Workflows are validated, versioned, compiled to DAG nodes, persisted, gated, and
resumable. Markdown-frontmatter is the Bridge; YAML/JSON Schema is Target.

The DAG represents work; the FSM represents runtime truth. Material graph changes
version state and invalidate affected approvals.

## Execution kernel

```text
request capability
 -> resolve exact tool/environment/action
 -> validate schema/dependency
 -> classify side effects/risk
 -> enforce all scopes
 -> obtain bound approval
 -> execute in selected environment
 -> classify process result
 -> normalize/redact
 -> persist evidence/events/usage/audit
```

The provider owns discovery and execution. Local, `wsl/kali-linux`, Docker,
SSH, and MCP are real identities, not metadata labels.

Capability families cover filesystem/repository, shell/process/service,
Git/build/test, HTTP/browser/search, network/scanners, containers/sandbox,
MCP/integrations, and evidence/reports.

Evidence is immutable provenance. Findings are typed state machines. SQLite is
canonical local state with append-only events. Memory is working/task/project/
repository scoped. UTOS owns resource strategy, not policy or completion.

## Interfaces

Current: Python CLI/TUI. Target: local FastAPI/events and TypeScript CLI. Later:
Tauri desktop using the same API. Interfaces never duplicate authority.

## Current map

| Concern | Current source | Maturity |
|---|---|---|
| Coordination/governance | `runtime/`, `governance/` | Current; Phase 0 fixes |
| Host/provider | `hostcontrol/`, `execution/` | Current; wiring gaps |
| Operational loop | `agent_loop.py`, `universal_agent.py` | Bridge |
| Workflow | `workflows/`, playbooks | Bridge |
| DAG/state | `planner/`, `schema/` | Foundation |
| Evidence/audit | `persistence/`, `observability/` | Foundation |
| Models | `models/`, `kernel/provider.py` | Foundation |
| Core Brain, UTOS, API/TS CLI | — | Target |

## Invariants

Model/tool output is untrusted; policy evaluates exact resolved actions; exit and
criteria determine success; scope covers outputs; state/evidence/audit are
correctness; consequential retry needs proof/review; cloud cannot add a second
policy path.
