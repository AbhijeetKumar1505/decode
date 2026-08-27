# Decode Documentation

Decode is an open, local-first cybersecurity agent. The bare `decode ❯`
prompt is a single **governed universal tool-use loop**: it discovers the tools
installed on the host, runs them (and your scripts) through the
`ExecutionCoordinator`, and preserves scope, approval, evidence, and audit on
every action. There is no hardcoded per-tool catalog and no separate skill stack.

**Last reconciled with source:** 2026-08-25

## Documentation status

- **Implemented** — working source exists and is exercised by tests.
- **Partial** — a foundation exists, but the documented contract is not uniformly enforced.
- **Planned** — a target design, not a statement of current behavior.

When documents disagree, repository policy (`AGENTS.md`) and source/tests are the
final evidence of implementation.

## Start here

| Document | Purpose |
|---|---|
| [Product](PRODUCT.md) | Vision, users, principles, constraints, and success metrics |
| [System architecture](SYSTEM_ARCHITECTURE.md) | How the universal agent, coordinator, and host control fit together |
| [Execution pipeline](EXECUTION_PIPELINE.md) | The normative intent → govern → execute → evidence path |
| [Security model](SECURITY_MODEL.md) | Trust boundaries, permission levels, scope, and confirmation policy |
| [Host control](HOST_CONTROL.md) | The governed host capabilities and the `/agent` loop |
| [Release roadmap](../ROADMAP.md) | Verified baseline, priorities, and release gates |
| [Development guide](DEVELOPMENT_GUIDE.md) | Contribution and implementation workflow |

## Architecture and execution

- [Technology stack](TECH_STACK.md)
- [Model routing](MODEL_ROUTING.md)
- [Memory architecture](MEMORY_ARCHITECTURE.md)
- [Database schema](DATABASE_SCHEMA.md)

## Extensibility and configuration

- [Plugin manifest lifecycle](PLUGIN_MANIFEST.md) — the trusted third-party extension path
- Markdown playbooks (`SKILL.md`) — see [AGENTS.md](../AGENTS.md) and `decode/skills/playbooks/`
- [Configuration](CONFIGURATION.md)
- [Prompt library](PROMPT_LIBRARY.md)

## Safety, quality, and research

- [Risk engine](RISK_ENGINE.md)
- [Testing strategy](TESTING_STRATEGY.md)
- [Threat model](threat-model.md)
- [Research specification](RESEARCH.md)
- [Architecture decisions](adr/README.md)

## Implementation notes

- [Memory engine](memory-engine.md)
- [Bootstrap engine](bootstrap-engine.md)
- [Audit layer](audit-layer.md)
- [Logging system](logging-system.md)

## Current approach (one paragraph)

Every action — whether typed at the bare prompt or via `/agent` — runs through
`UniversalAgent.run_tool_loop`, a bounded plan → call tool → observe → iterate
loop. The loop's tools are the governed **host capabilities** (`decode/hostcontrol/`,
owned by `HostAgent`): file read/write/edit/search, process and service control,
`list_tools` (a `$PATH` scan for tool discovery), `shell_command` (run any
installed CLI or script as an argument vector), and `host_session` (stateful
sequences). Reusable procedures are authored as **markdown playbooks**, not Python
wrappers. Everything routes through `ExecutionCoordinator`, which applies the
filesystem scope, target scope, per-command risk classification, permission mode,
bound approval, audit trail, and hashed evidence. Persistence is SQLite (optional
MongoDB); model selection is governed by data-locality-aware routing. Removed from
earlier designs: the multi-agent roster, the tool/capability registry and Kali
catalog, mission/workflow runners, the event bus, and the planned
FastAPI/PostgreSQL/Redis/Qdrant service tier.

## Documentation maintenance

For behavior changes, update in this order: repository policy (`AGENTS.md`),
applicable ADR (when the decision is durable), the affected subsystem doc, and the
release roadmap. Verify relative Markdown links and referenced repository paths.
Never use real target data, credentials, or operational registries in docs.

Repository-level policies remain canonical in [AGENTS.md](../AGENTS.md), the
[contributing guide](../CONTRIBUTING.md), [security policy](../SECURITY.md),
[license](../LICENSE), and [release roadmap](../ROADMAP.md).
