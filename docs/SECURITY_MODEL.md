# Security Model

## Security objective

Decode assists with authorized cybersecurity work while ensuring that models, agents, plugins, tools, and remote workers cannot exceed user-defined scope or bypass permission and audit controls.

This document complements the implementation-level [threat model](threat-model.md) and repository [security policy](../SECURITY.md).

**Maturity:** the execution and governance contract is implemented. Every tool the
universal agent calls — host operations, `list_tools`, `shell_command`,
`host_session`, and markdown playbooks — runs through `ExecutionCoordinator`.
Per-command risk is classified before the gate; required targets fail closed when
omitted, including under `allow_all`; provider calls must match the authorized
executor family; approvals are materially bound and expiring; terminal telemetry is
mandatory; and raw results are retained through protected immutable references. Raw
model-generated shell strings are not an execution path — only the governed
`shell_command` argument vector is.

## Trust boundaries

```text
User identity and project policy
            |
            v
Trusted kernel policy boundary
   |          |          |
Models     Plugins     Executors
untrusted  untrusted   constrained
   |          |          |
Retrieved content     Security tools/targets
        untrusted and potentially hostile
```

Model output is never trusted as authorization, a shell command, a verified fact, or a memory mutation without validation.

## Permission levels

| Level | Default behavior | Examples |
|---|---|---|
| READ | Allow when data and scope policy permit | Local metadata, passive public lookup |
| WRITE | Require human approval | Target probes, file changes, service actions |
| DESTRUCTIVE | Deny unless engagement override exists; still require approval | Exploitation, credential attacks, disruptive changes |

`CommandPolicy.classify` types the exact argument vector, so a specific command's resolved risk can exceed the `shell_command` capability's WRITE baseline (and a DESTRUCTIVE command may not run via `shell_command` at all).

## Scope enforcement

- Target allowlists support addresses, CIDRs, hosts, URLs, and wildcard domains.
- Empty scope denies target execution.
- Subtasks inherit a subset of parent scope.
- DNS resolution cannot silently widen scope.
- Scope is checked at plan validation and immediately before execution.
- Out-of-scope attempts are denied and audited.

## Command validation

- Prefer direct argument vectors over shell strings.
- Validate targets, ports, paths, enums, ranges, and resource limits.
- Resolve paths and symlinks before access decisions.
- Reject unknown raw flags unless an explicit expert policy permits them.
- Redact secrets in command display, logs, events, and errors.
- Bind approval to action, target, normalized arguments, material command, executor, risk, privileges, opaque credential references, and expiry.

## Sandbox and executor policy

- Local execution is explicit and carries host-impact risk.
- Docker execution uses least privilege, controlled mounts, resource limits, and no unrestricted daemon/socket access.
- WSL is a separate Linux boundary but not automatically a security sandbox.
- SSH validates host identity and uses scoped credentials.
- MCP servers are external principals with declared tool contracts.
- Malware and untrusted artifact execution requires an isolated analysis environment.

## Secrets handling

- Load secrets from environment variables or a dedicated secret provider.
- Never place secrets in prompts unless the selected action explicitly requires them.
- Use opaque secret references in tasks and events.
- Redact known secret fields from logs and exceptions.
- Scope credentials by project, capability, target, and expiry.
- Do not store secrets in generated registries, source control, embeddings, or model training data.
- Rotate secrets after suspected exposure.

## Credential storage

Current SQLite artifacts can mark data as sensitive, but production credential storage requires encryption at rest, OS/key-vault integration, access audit, and deletion guarantees. Until those controls exist, avoid durable raw credential storage where possible.

## Prompt-injection protection

- Treat web pages, tool output, documents, email, code, and retrieved memory as untrusted data.
- Keep policy and tool schemas in trusted channels.
- Delimit external content and identify its provenance.
- Ignore embedded requests to reveal secrets, change scope, install software, or execute tools.
- Validate all model-proposed actions through the same deterministic policy pipeline.
- Test direct, indirect, multi-turn, and memory-based injection.

## Plugin verification

Third-party plugins use the P2 manifest lifecycle. Discovery and conformance parse source without importing it; manifests require a schema version, compatibility range, capability and permission declarations, sandbox request, and SHA-256 entrypoint digest. Lifecycle state is persisted locally and supports explicit install, enable, disable, revocation, upgrade, rollback, and uninstall. Revoked packages cannot be enabled.

A manifest never grants scope, approval, credentials, memory, executor access, or network access. Enabled third-party packages must request the container profile; its generated Docker command disables networking, uses a read-only root filesystem, drops capabilities, enables no-new-privileges, and sets process, CPU, memory, and temporary-filesystem limits. Networked plugin containers are denied until target-scoped container networking is implemented and tested.

The legacy in-tree loader remains trusted application code and is quarantined from direct execution through the shared coordinator path.
## Audit logs

Audit records include actor, action/capability, target, risk, decision, approval, time, policy version, and correlation ID. Logs are append-oriented, access-controlled, rotated, and protected from silent modification in production profiles.

Secrets and unnecessary raw content are excluded. Denials are auditable alongside executions.

Execution output is stored in permission-restricted, immutable evidence files with a stable identifier, SHA-256 hash, and byte length. Operational stores and telemetry carry only the protected reference. If mandatory evidence capture or terminal telemetry fails, consequential execution fails closed and does not expose the raw result.

## User confirmation policy

Confirmation is required when:

- Risk is WRITE or DESTRUCTIVE.
- A command installs software or changes configuration.
- Credentials or sensitive artifacts will be used.
- Privilege elevation is required.
- The plan changes materially after approval.
- Execution leaves the local environment or sends sensitive data to a provider.

The prompt presents concrete target, action, executor, side effects, and risk.

## Data classification

Suggested classes:

- `public`
- `internal`
- `confidential`
- `restricted`
- `secret`

Models, plugins, memory stores, and events declare the maximum class they may receive. The strictest source classification propagates to derived data unless an approved sanitization process lowers it.

## Network policy

- Outbound destinations are restricted by capability and executor.
- Target scope applies after redirects and DNS resolution.
- Rate and concurrency limits protect targets and networks.
- Passive and active operations are distinguishable.
- Proxy use and source identity are explicit and auditable.

## Supply-chain security

- Pin and scan dependencies.
- Produce release SBOMs.
- Sign release artifacts.
- Verify plugin and container provenance.
- Minimize build credentials.
- Review updates that change tool, model, parser, or policy behavior.

## Failure policy

Fail closed when scope, permission, mandatory audit, or critical validation is unavailable. Optional model, vector, or distributed services may degrade capability but cannot weaken controls.

## Security testing

Required suites include scope bypass, command injection, path traversal, prompt injection, plugin escalation, secret redaction, approval replay, parser fuzzing, event forgery, remote executor identity, and audit completeness.

## Responsible use

Decode is intended for systems the user owns or is explicitly authorized to assess, defensive investigation, education, and controlled research. Technical controls supplement but do not replace legal authorization and professional judgment.
