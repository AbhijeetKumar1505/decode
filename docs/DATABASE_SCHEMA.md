# Database and Event Schema

**Status:** Current SQLite stores are foundations; normalized v2 schema is Target

SQLite is canonical local state. Truth-defining state/events are transactional.
Large/raw evidence stays in protected artifact storage with hashes/metadata in
SQLite. Version schemas and Alembic migrations before API/TypeScript separation.

| Entity | Purpose |
|---|---|
| projects | isolation, workspace, policy, retention |
| sessions/tasks | lifecycle, objective, status, mode, budgets |
| workflow_runs | definition version/fingerprint/status |
| task_graphs/nodes/edges | versioned DAG and attempts |
| events | append-only lifecycle/security facts |
| tool_calls | resolved action and normalized result |
| approvals | digest, identity, decision, expiry |
| evidence/artifacts | provenance, hash, protected location |
| findings | candidate through validation/regression |
| memory_entries | provenance-linked scoped memory |
| usage_records/budgets | UTOS accounting/reservations |
| schema_migrations | versions/checksums |

Common fields: stable ids, project/task keys, schema version, timestamps,
provenance, classification, and optimistic version. Unknown usage remains null.

Events are append-only; materialized state records causative event and expected
prior version. Evidence has hash, size/type, producer/provider, time,
classification, storage ref. Findings reference validation evidence.

Store credential references, not values. Encrypt where available, separate
evidence access, redact exports, audit access. Backups inherit highest data class.

Index status/readiness/event sequence/evidence hash/finding state/memory
project-kind-freshness/usage/model-time/approval digest-expiry.

Every change needs forward migration, rollback or explicit irreversibility,
fixture tests, backup guidance, and continuation note. AWS databases are Deferred.
