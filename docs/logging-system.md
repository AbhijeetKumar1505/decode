# Structured Logging

`LoggingService` in `decode/logging_service.py` writes structured execution records and output references under the configured logs directory.

## Current status

The service is implemented and mandatory across coordinator-backed public execution boundaries. Success, execution failure, pre-execution denial, approval failure, dependency block, timeout, cancellation, and mandatory telemetry failure produce a structured record. Boundary inventories prevent a new public execution method from silently bypassing this contract.

## Execution record

```json
{
  "timestamp": "2026-07-31T12:00:00+00:00",
  "tool": "skill_name",
  "command": "redacted command",
  "status": "success",
  "duration": 12.4,
  "output_file": "logs/skill_name/result.json",
  "error": "",
  "metadata": {}
}
```

Command and error fields are redacted by the coordinator. Large or sensitive raw output is captured in protected immutable evidence storage; `output_file` and metadata carry its reference rather than copying raw output into logs.

```python
from decode.logging_service import LoggingService

logger = LoggingService()
logger.log_execution(
    tool="skill_name",
    command="redacted command",
    status="success",
    duration=12.4,
)
```

## Retention

The service does not currently implement automatic rotation, compression, or deletion. Deployments must define those controls explicitly. Planned retention settings in configuration documents are target requirements, not current behavior.

See [Audit Layer](audit-layer.md), [Execution Pipeline](EXECUTION_PIPELINE.md), and [Security Model](SECURITY_MODEL.md).
