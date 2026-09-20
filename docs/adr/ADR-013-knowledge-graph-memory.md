# ADR-013: Structured Provenance-Linked Memory

**Status:** Accepted; amended for v2

## Decision

Use working/task/project/repository memory with provenance, classification,
freshness, isolation, and event/evidence references. Use relationship graphs
where useful. Embeddings are optional.

## Consequences

Retrieval is untrusted; conflicts explicit; summaries derived. Retention/export/
deletion and poisoning tests are mandatory.
