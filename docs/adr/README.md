# Architecture Decision Records

ADRs record durable Decode architecture choices. `Accepted` decisions govern current work; `Research` decisions define an experiment rather than a production commitment.

Records for approaches that were later removed during the universal-agent pivot
(event-driven kernel, universal tool registry, Kali integration, multi-agent
design, dynamic plugin loading, tool-capability discovery) and for infrastructure
that was never adopted (Redis Streams, PostgreSQL, Qdrant, FastAPI, Neural Schema)
have been deleted rather than kept as stale history; the current design is
described in [../SYSTEM_ARCHITECTURE.md](../SYSTEM_ARCHITECTURE.md).

| ADR | Decision | Status |
|---|---|---|
| [001](ADR-001-why-python.md) | Python as the primary implementation language | Accepted |
| [004](ADR-004-plugin-architecture.md) | Plugin architecture | Accepted |
| [007](ADR-007-multi-model-routing.md) | Multi-model routing | Accepted |
| [013](ADR-013-knowledge-graph-memory.md) | Knowledge graph memory | Accepted |
| [014](ADR-014-permission-based-execution.md) | Permission-based execution | Accepted |
| [015](ADR-015-safety-confirmation-layer.md) | Human safety confirmation | Accepted |
| [018](ADR-018-audit-logging.md) | Mandatory audit logging | Accepted |
| [019](ADR-019-local-first-execution.md) | Local-first execution | Accepted |
| [020](ADR-020-explainable-decisions.md) | Explainable system decisions | Accepted |

## Process

1. Copy the structure of an existing ADR.
2. Describe context, decision, and consequences.
3. Link relevant product, security, and implementation documents.
4. Review security, migration, and reversal implications.
5. Update status rather than rewriting history; superseding ADRs link both records.
