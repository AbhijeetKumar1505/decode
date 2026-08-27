# Testing Strategy

## Objectives

Testing establishes correctness, policy enforcement, reproducibility, parser resilience, and safe failure. Passing a happy-path unit test is not sufficient for a cybersecurity orchestration system.

## Test pyramid

```text
          Controlled end-to-end labs
       Integration and contract tests
   Unit, schema, policy, and parser tests
```

Most tests remain deterministic, local, and offline.

## Unit testing

Cover:

- Pydantic models and validation.
- Capability and agent selection.
- Scope matching.
- Permission and risk decisions.
- Planner/DAG behavior.
- Command argument construction.
- Parsers and normalization.
- Memory, persistence, logging, audit, and feedback.

## Integration testing

Exercise boundaries between the agent loop, coordinator, host capabilities, executor, persistence, and observability. Use fake providers and subprocess fixtures. Docker/WSL/SSH/MCP integrations are opt-in when dependencies are available.

## Security testing

- Command injection and quoting across platforms.
- Path traversal and symlink escapes.
- Scope bypass through URLs, DNS, redirects, IPv6, and CIDRs.
- Approval replay and changed-command detection.
- Secret redaction and accidental persistence.
- Prompt injection through tool output and memory.
- Plugin privilege escalation.
- Malformed event and API payloads.
- Audit tampering and missing-audit failure.
- Dependency and supply-chain checks.

## Agent testing

Each agent is tested for capability ownership, bounded memory access, missing tools, denied approval, timeout, cancellation, normalization, partial results, and stable errors.

## LLM evaluation

Model-dependent behavior uses versioned datasets and records provider/model, prompt version, parameters, and date. Metrics include task correctness, structured-output validity, evidence use, unsupported claims, scope adherence, unsafe action proposals, latency, and cost.

Unit tests never require live paid model access.

## Prompt regression

- Golden schema fixtures.
- Adversarial direct and indirect injections.
- Long-context truncation.
- Conflicting instructions.
- Sensitive-data exfiltration.
- Provider/model comparison.
- Refusal and safe-degradation behavior.

## Plugin testing

Plugin conformance covers manifest/schema, compatibility, dependency failures, import side effects, permission bounds, sandbox/profile, lifecycle, event emission, and uninstall/disable behavior.

## Tool and parser testing

- Version probe fixtures.
- Argument-vector snapshots.
- Machine-output fixtures from supported versions.
- Truncated, malformed, localized, and unexpected output.
- Large-output bounds.
- Non-zero exit with useful partial output.
- Evidence hash and provenance.

Fixtures come from legal controlled environments and contain no real credentials.

## Persistence and migration testing

- Fresh schema creation.
- CRUD and foreign-key behavior.
- Concurrent local access.
- Backup/restore.
- Migration from every supported release.
- Failure rollback.
- Project isolation.
- Retention and deletion across semantic indexes.

## Performance testing

Measure planner latency, registry scan time, parser throughput, database queries, memory retrieval, event lag, and report generation. Define budgets before optimization.

## Stress and resilience testing

- High task/event counts.
- Slow and unavailable providers.
- Executor disconnect.
- Process timeout and cancellation.
- Disk full and read-only storage.
- Corrupted registry/index.
- Restart during workflow execution.
- Duplicate event delivery.

Consequential external actions use simulators or disposable labs.

## End-to-end labs

Use isolated, resettable environments with explicit scope. Validate full intent-to-evidence workflows and audit completeness. Never point CI security tools at public or production targets.

## Required commands

```text
ruff check .
python -m pytest tests/
```

## Coverage gates

Prioritize branch coverage for governance, safety, scope, command construction, plugins, secrets, and migrations. New policy code requires positive, negative, and boundary cases.

## Flaky tests

Quarantine is temporary and tracked. Tests may not silently retry until passing. Record the suspected nondeterminism and owner.

## Release criteria

- Lint and required tests pass.
- No unresolved critical/high security regressions.
- Migrations and rollback limits are verified.
- Prompt/model benchmark safety does not regress.
- Audit/log/feedback completeness passes.
- Documentation status matches implementation.
