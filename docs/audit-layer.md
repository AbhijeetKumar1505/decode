# Audit Layer

`AuditLayer` in `decode/audit.py` writes append-oriented JSONL records for security-relevant events. Audit is distinct from ordinary application logging.

## Current status

The audit service and query API are implemented. Coordinator-backed public execution entry points emit an audit record for every terminal outcome, including success, execution failure, denial, approval failure, dependency block, timeout, cancellation, and mandatory telemetry failure. Table-driven inventories guard the P0 boundary; non-execution lifecycle events retain their subsystem-specific audit behavior.

## Execution event

```json
{
  "id": "generated-uuid",
  "timestamp": "2026-07-31T12:00:00+00:00",
  "event": "tool_execution",
  "tool": "skill_name",
  "target": "192.0.2.10",
  "risk": "WRITE",
  "approved": true,
  "detail": "non-sensitive summary",
  "metadata": {}
}
```

Use legal synthetic targets in examples. Do not copy credentials, tokens, raw sensitive payloads, or full commands containing secrets into audit details.

Executed outcomes use `tool_execution` with their true terminal status in non-sensitive metadata. Requests blocked before execution use `rejection`. Evidence identifiers, paths, hashes, and byte lengths may be referenced; raw evidence is not embedded in audit records.

```python
from decode.audit import AuditLayer

audit = AuditLayer()
audit.record_execution(
    tool="skill_name",
    target="192.0.2.10",
    risk="WRITE",
    approved=True,
)
```

## Retention and integrity

Automatic 30/90-day rotation or deletion is not implemented by `AuditLayer`. Deployments must define retention, protected export, access control, and legal-hold behavior. The target design adds chained hashes or signed batches and independent retention monitoring; see [Database Schema](DATABASE_SCHEMA.md) and [Security Model](SECURITY_MODEL.md).
