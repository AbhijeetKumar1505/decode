# Audit Layer

**Status:** Current foundation; v2 event contract Target

Audit records who/what proposed, authorized, executed, and verified each material
action without becoming a secret/raw-evidence store.

Fields: event/time/schema, task/workflow/node/state versions, actor/model role,
capability, action digest, target/provider, risk/scope decision, approval,
outcome/status/error, evidence/usage references, and public reason codes.

Never include raw credentials, cookies, keys, sensitive stdin, or unredacted
payloads. Raw output belongs in protected evidence.

Events cover task/workflow/state, resolution, policy, approval, execution,
evidence/finding, memory, routing/usage, migration, extension, and retention.

Events are append-only, ordered per task, schema-versioned, and transactionally
linked where required. Consequential work fails closed if audit cannot commit.
Apply project isolation, retention, export/deletion/hold, integrity, and access
controls. Audit is not memory.
