# Database Schema

## Status

The current local profile uses SQLite at `data/decode.db`. A PostgreSQL team profile is planned. This document distinguishes the implemented schema from the target service schema.

## Current SQLite tables

### `sessions`

Stores goal, target focus, status, and timestamps.

### `targets`

Stores session-scoped hostname, address, domain, operating system, first/last seen timestamps, and JSON metadata.

### `ports`

Stores target-scoped port, protocol, state, service, product, version, extra information, and observation timestamps.

### `findings`

Stores session/target relationships, title, description, severity, category, CVE, ATT&CK technique/tactic, confidence, evidence IDs, and creation time.

### `evidence`

Stores session/finding relationships, evidence type, label, JSON data, source, and creation time.

### `projects`

Stores project identity, name, scope, and creation time.

### `artifacts`

Stores project/session-scoped typed key/value artifacts with a sensitive flag and creation time.

SQLite enables foreign keys and WAL mode. The source of truth is `decode/persistence/store.py`.

## Target logical schema

| Table | Purpose |
|---|---|
| `projects` | Tenant/project boundary, policy, retention, and status |
| `sessions` | User interaction and assessment-session lifecycle |
| `tasks` | Planned work, dependencies, state, limits, and idempotency |
| `events` | Versioned lifecycle event envelopes |
| `executions` | Tool/model/executor attempts and outcomes |
| `tool_calls` | Resolved tool, normalized arguments, risk, and command metadata |
| `plugins` | Installed plugin identity, version, trust, and state |
| `agents` | Registered agent version and capabilities |
| `permissions` | Policy decisions, approvals, actors, and expiry |
| `memories` | Scoped, classified, provenance-linked memory |
| `knowledge_nodes` | Versioned graph entities |
| `knowledge_edges` | Versioned graph relationships |
| `embeddings` | Optional vector index references and source lineage |
| `models` | Model registry and evaluation metadata |
| `audit_logs` | Append-only security/audit events |
| `findings` | Security findings with lifecycle and confidence |
| `evidence` | Immutable evidence metadata and artifact references |
| `artifacts` | Protected file/object metadata and hashes |

## Common columns

Most target tables include:

- UUID primary key.
- `project_id`.
- UTC `created_at` and `updated_at`.
- Schema/version field.
- Actor or source reference.
- Classification.
- Optimistic concurrency version where mutable.

## Relationships

```text
project
  +-- sessions
  |     +-- tasks
  |     |     +-- executions
  |     |     |     +-- tool_calls
  |     |     +-- events
  |     +-- findings
  |           +-- evidence
  +-- plugins
  +-- agents
  +-- permissions
  +-- memories
  +-- knowledge_nodes -- knowledge_edges
  +-- artifacts
  +-- audit_logs
```

## Evidence storage

Large or binary evidence belongs in protected object/filesystem storage. The database stores digest, size, media type, source, custody history, encryption metadata, retention, and object reference.

Evidence content is immutable. Corrections create new derived artifacts.

## Secret data

Raw credentials and API keys should live in a secret provider, not ordinary database columns. Records store opaque references, classification, owner, scope, and expiry. Current sensitive SQLite artifacts are a local prototype and must not be treated as an enterprise vault.

## Multi-tenancy

The planned PostgreSQL profile enforces project isolation in application policy and database row-level security. Service accounts receive only required table and project access.

## Audit integrity

Audit rows are append-only. Production deployments should add chained hashes or signed batches, restricted delete/update privileges, protected export, and independent retention monitoring.

## Embeddings

Embedding records retain source memory/evidence ID, model/version, dimensions, project, classification, digest, and deletion state. Vector deletion is part of source deletion.

## Migrations

- Use ordered, transactional migrations.
- Back up and test restore before destructive changes.
- Provide forward migration and documented rollback limits.
- Never silently discard unknown fields or evidence.
- Test migrations from every supported release.
- Local SQLite and PostgreSQL schemas share logical models but may use different physical types.

## Indexing

Index task state/dependencies, event correlation/time, execution task/time, finding project/severity, evidence finding/hash, memory project/type/time, knowledge node type/name, and audit project/time/type.

## Retention

Retention is project-configurable by data class. Expiration jobs emit audit events, honor legal holds, and delete derived semantic indexes and replicas. Secret values are never copied into audit tombstones.
