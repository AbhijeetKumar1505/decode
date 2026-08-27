# Memory Architecture

## Goals

Decode memory supports continuity and correlation without turning untrusted tool or model output into permanent truth. Every durable memory has scope, provenance, sensitivity, retention, and deletion semantics.

## Current memory layers

| Layer | Implementation | Scope | Status |
|---|---|---|---|
| Session memory | In-process `SessionMemory` and context manager | One mission/session | Implemented |
| Project memory | SQLite artifacts through `ProjectMemory` | One engagement across sessions | Implemented |
| Knowledge memory | In-memory knowledge graph | Cross-session facts | Partial |
| Semantic retrieval | FAISS with OpenRouter embeddings prototype | Configured local index | Partial/research |
| Evidence store | SQLite metadata and evidence files/hashes | Project/session | Implemented |

## Memory classes

### Conversation memory

Stores the minimal dialogue and decisions needed to continue a session. Long transcripts are summarized with references to original records. Hostile content remains labeled as untrusted.

### Project memory

Stores targets, findings, artifacts, notes, and engagement context. Access is isolated by project. Sensitive artifact types such as credentials, tokens, cookies, JWTs, API keys, passwords, and secrets require protected storage and redacted rendering.

### Recon memory

Tracks observed hosts, ports, services, technologies, relationships, timestamps, and source evidence. Observations are time-bound and can become stale.

### Host profiles

Aggregate observations about a host without overwriting provenance. Conflicting observations coexist with timestamps and confidence.

### Attack history

Records approved plans, tool calls, results, and user decisions. It is an audit/replay source, not an instruction to repeat actions automatically.

### Knowledge graph

Represents entities and relationships such as assets, vulnerabilities, techniques, mitigations, tools, and evidence. Every learned edge links to provenance and a confidence or verification state.

### Semantic index

Indexes permitted text or derived representations for retrieval. Embeddings inherit the source data’s classification and deletion requirements.

## Write policy

Memory writes must specify:

- Project and session scope.
- Author: user, tool, model, plugin, or system.
- Source/evidence reference.
- Timestamp.
- Data classification and sensitivity.
- Verification status and confidence.
- Retention policy.
- Schema version.

Tool and model outputs default to observations, not verified facts.

## Read policy

Retrieval filters by:

- Project and user authorization.
- Task purpose.
- Data classification.
- Agent memory scope.
- Time and staleness.
- Verification state.
- Token/context budget.

Secrets are returned as opaque references unless the executing capability explicitly requires their value.

## Retrieval

The target hybrid strategy combines:

1. Exact structured queries.
2. Knowledge-graph traversal.
3. Keyword search.
4. Optional semantic search.
5. Recency, provenance, and confidence ranking.

Retrieved items include citations to their source records. A model cannot silently promote a retrieved item to verified state.

## Compression

Compression reduces context size, not evidence:

- Immutable raw evidence remains available.
- Summaries link to source IDs.
- Critical targets, findings, approvals, and unresolved conflicts are preserved.
- Compression records the model/algorithm and version used.
- Summaries can be regenerated.

## Forgetting and deletion

- Session scratch data expires at session end unless promoted.
- Project retention follows explicit policy.
- User-requested deletion covers operational data, semantic vectors, derived summaries, and replicas.
- Audit records follow legal and policy retention and may be pseudonymized rather than silently removed.
- Deletion events are auditable without retaining deleted secret values.

## Learning

Learning means recording evaluated experience, not autonomous modification of permissions or code. An experience is eligible for reuse only after:

- Sensitive-data filtering.
- Scope and provenance checks.
- Success/quality evaluation.
- Deduplication and conflict handling.
- Versioned storage.
- User or policy authorization.

## Memory poisoning defenses

- Label external content as untrusted.
- Separate instructions from observations.
- Require provenance for durable claims.
- Apply schema and length validation.
- Detect conflicting and anomalous updates.
- Restrict plugin write scopes.
- Evaluate retrieval against prompt-injection test sets.
- Provide project-level reset, export, and deletion controls.

## Storage profiles

### Local

SQLite, filesystem evidence, in-process knowledge graph, and optional FAISS. This is the current primary profile.

### Team

Planned PostgreSQL operational store, protected object storage, and optional Qdrant semantic index. Tenant isolation and encryption are adoption requirements.

## Observability

Record retrieval queries, selected memory IDs, filters, write decisions, compression operations, and deletion events without logging secret values.
