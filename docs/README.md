# De-code Documentation

**Architecture generation:** v2 transition
**Last reconciled:** 2026-09-17

De-code is a governed engineering and authorized-security execution system. The
model supplies cognition; deterministic workflows, state, policy, capabilities,
evidence, memory, verification, and resource governance supply competence.

## Read this first

1. [Product Constitution](PRODUCT.md)
2. [Canonical Build Plan](BUILD_PLAN.md)
3. [Continuation Ledger](CONTINUATION.md)
4. [System Architecture](SYSTEM_ARCHITECTURE.md)
5. [Repository Migration Map](REPOSITORY_STRUCTURE.md)

Source and tests define current behavior. The build plan defines sequence. The
continuation ledger is the session handoff source.

## Maturity labels

- **Current** — present in source and supported by tests.
- **Bridge** — intentional temporary migration implementation.
- **Target** — accepted v2 design, not yet implemented.
- **Research** — hypothesis requiring evaluation.
- **Deferred** — outside the current build phase.

## Architecture

- [System Architecture](SYSTEM_ARCHITECTURE.md)
- [Core Brain and Active Brain](BRAIN_ARCHITECTURE.md)
- [Workflows](WORKFLOWS.md)
- [Execution Pipeline](EXECUTION_PIPELINE.md)
- [Host and Environment Control](HOST_CONTROL.md)
- [UTOS](UTOS.md)
- [Technology Stack](TECH_STACK.md)
- [Database Schema](DATABASE_SCHEMA.md)
- [Memory Architecture](MEMORY_ARCHITECTURE.md)
- [Model Routing](MODEL_ROUTING.md)

## Security and evidence

- [Security Model](SECURITY_MODEL.md)
- [Risk Engine](RISK_ENGINE.md)
- [Threat Model](threat-model.md)
- [Audit Layer](audit-layer.md)
- [Structured Logging](logging-system.md)
- [Testing Strategy](TESTING_STRATEGY.md)

## Interfaces and engineering

- [Configuration](CONFIGURATION.md)
- [MCP](MCP_SERVER.md)
- [Extensions](PLUGIN_MANIFEST.md)
- [Prompt Contracts](PROMPT_LIBRARY.md)
- [Bootstrap](bootstrap-engine.md)
- [Development Guide](DEVELOPMENT_GUIDE.md)
- [Pre-AWS Roadmap](PRE_AWS_ROADMAP.md)
- [Research](RESEARCH.md)
- [Architecture Decisions](adr/README.md)
- [Memory Implementation Note](memory-engine.md)

## Authority and maintenance

Use repository/user policy, source/tests, accepted ADRs, the build plan, then
subsystem docs. Do not mark targets implemented without source/test evidence.
Never place credentials, real target data, or private engagement details in docs.

AWS is Deferred until local Linux, Kali WSL, and Docker release gates pass.
