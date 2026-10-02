# ADR-013: Structured Provenance-Linked Memory

**Status:** Accepted; amended for v2

## Decision

Use working/task/project/repository memory with provenance, classification,
freshness, isolation, and event/evidence references. Use relationship graphs
where useful. Embeddings are optional.

The Engineering Knowledge Layer separates event memory, evidence-backed
knowledge, and reasoning. Project-scoped SQLite is the first graph backend;
Obsidian-compatible Markdown is an optional read-only interface for authored
notes, not the source of task, approval, audit, or raw-evidence truth. UTOS
budgets retrieval but cannot promote or authorize knowledge. Model-generated
claims remain candidates until independently validated. A separate graph
database and two-way vault synchronization remain Research/Deferred until
measured and security-reviewed.

## Consequences

Retrieval is untrusted; conflicts explicit; summaries derived. Retention/export/
deletion and poisoning tests are mandatory.
Graph edges must verify both endpoints share project ownership before traversal
or export. Vault adapters require explicit path scope, sensitive-data controls,
conflict handling, and auditable promotion decisions.
