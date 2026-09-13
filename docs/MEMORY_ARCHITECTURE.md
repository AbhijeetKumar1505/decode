# Memory Architecture

## Goals

Decode memory supports continuity and correlation without turning untrusted tool or model output into permanent truth. Every durable memory has scope, provenance, sensitivity, retention, and deletion semantics.

## Current memory layers

| Layer | Implementation | Scope | Status |
|---|---|---|---|
| Session memory | In-process `SessionMemory` and context manager | One mission/session | Implemented |
| Project memory | SQLite/Mongo artifacts through `ProjectMemory` | One engagement across sessions | Implemented |
| User memory | `UserMemory`, explicit `user_id` | One local user identity | Implemented |
| Global memory | `GlobalMemory`, explicitly enabled | Shared within the configured store | Implemented |
| Knowledge memory | In-memory knowledge graph | Cross-session facts | Partial |
| Semantic retrieval | Opt-in `SelfLearningMemory` backend for `HybridRetriever` | One project per local snapshot | Implemented (explicit embedding backend) |
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

## Implemented lifecycle API (Phase 4)

`MemoryManager(store, project_id=..., user_id=..., include_global=False)` exposes
`project`, optional `user`, and optional `global_memory` facades. An absent project
returns no project artifacts; it never broadens retrieval to all projects. Global
retrieval requires `include_global=True`. These identities are caller-supplied
local scope boundaries; authenticated accounts and roles remain Phase 6 work.
Construct operational stores through `create_store()`.

Each facade provides `remember`, `recall`, `edit`, `history`, `export`, and `forget`.
`remember` accepts optional timezone-aware `expires_at` and finite `confidence`
from 0 to 1. Expired artifacts are excluded from normal reads, search, and export;
explicit history retains them until deletion. Clearing expiry with
`edit(..., expires_at=None)` makes the current record readable again.

`edit(id, expected_version=1, value="revised observation")` preserves the previous
record and atomically increments its version. A stale version or different owner
is rejected. Scope, type, IDs, and creation time cannot be edited. Sensitivity
cannot be downgraded. `history` and `export` redact sensitive keys, values, and
prior versions by default; trusted store reads and `recall` return raw values.
Prompt-oriented exact retrieval excludes sensitive artifacts. `forget` removes
an artifact and its history; raw evidence is unaffected.

SQLite upgrades existing artifact rows on opening. Mongo reads older documents
with equivalent defaults and versions them on first edit. Revisions live with
the artifact, so Mongo edits need no multi-document transaction. No background
expiry purge or database encryption is implemented. The broader provenance,
policy-based promotion, and automatic retention policies above remain targets.

## Opt-in semantic backend

Pass `SelfLearningMemory(path, project_id=..., embeddings=backend)` as
`MemoryManager(..., semantic_memory=...)`. The backend must provide
`embed_query(text)` and `embed_documents(texts)`. It can run locally;
`OpenRouterEmbeddings` is an explicit hosted choice. Callers must authorize the
embedding provider and the data sent to it. No embedding provider is constructed
or called by default, including during universal-agent startup.

The local snapshot atomically stores text, vectors, project identity, and embedding
model identity together. Reopening rejects another project's or model's snapshot.
Retrieval labels semantic results unverified, limits results to existing vectors,
and degrades to no semantic results on query/backend failure without logging
exception payloads. Exact artifacts and graph results remain available.

Only explicitly supplied observations are indexed; artifacts are not automatically
copied into the index. Sensitive-flagged experiences and recognized secret patterns
are rejected before embedding. This filter cannot identify every possible secret;
callers must classify text before adding it. Artifact edit/expiry therefore applies
to artifact records, not independently supplied semantic observations. Project
memory deletion clears its attached semantic backend. Legacy prototype index files
are not loaded or rewritten automatically. Concurrent writers to one semantic
snapshot are unsupported; use one owner per index. Automatic learning and
promotion of observations into verified knowledge remain research.
