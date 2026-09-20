# Security Policy

## Intended use

De-code is for engineering, education, defensive analysis, research, and
security testing of systems the operator owns or has explicit written
authorization to assess. It is not an unrestricted exploitation system.

## Prohibited use

- Accessing, scanning, testing, or modifying systems without authorization.
- Illegal, abusive, or provider-policy-violating activity.
- Using Decode to conceal attribution, persistence, credential theft, or destructive impact.

Operators are responsible for applicable law, engagement rules, data handling, and target authorization.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability in Decode. Until a private security contact is published, use the repository host's private vulnerability-reporting feature. The project must configure and publish a monitored security contact before a public production release.

Include the affected version, reproduction steps, impact, relevant logs with secrets removed, and a suggested mitigation if known. Maintainers should acknowledge receipt promptly, coordinate disclosure, and publish a tested fix and advisory based on severity. Response times are targets, not guarantees.

## Current security controls

| Control | Current state |
|---|---|
| Risk classification | Exact resolved actions are classified as `READ`, `WRITE`, or `DESTRUCTIVE` |
| Scope policy | Allowlist; empty scope denies target execution |
| Human approval | `WRITE` requires approval; `DESTRUCTIVE` also requires an explicit engagement override |
| Execution governance | `ExecutionCoordinator` is the single pre-execution decision point |
| Model authority | Models, prompts, playbooks, plugins, and tool output cannot grant permission |
| Execution providers | Local, Docker, WSL, configured SSH, and MCP foundations |
| Evidence integrity | SHA-256 and chain-of-custody foundations |
| Observability | Structured log, audit, and feedback services exist |
| Provider keys | Loaded from environment configuration and must never be logged |

## Known limitations

The current Python baseline is not the completed v2 security architecture.
Phase 0 still has known process-result, strict-schema, shell-metacharacter,
output-path, provider-binding, discovery-result, and governed browsing/search
gaps. Local, WSL, Docker, SSH, and MCP execution are not inherently isolated.
Storage encryption, multi-user authorization, a stable network control plane,
and cloud deployment are not complete.

Markdown playbooks and declarative plugin packages are untrusted guidance and
configuration, never executable authority. Raw model-generated shell is blocked;
the governed command capability is the only sanctioned general CLI path.

Do not claim complete enforcement until the applicable gates in the
[build plan](docs/BUILD_PLAN.md) pass. See the canonical
[security model](docs/SECURITY_MODEL.md), [risk engine](docs/RISK_ENGINE.md),
and [threat model](docs/threat-model.md).

## Security architecture rules

- Scope covers network targets, filesystem reads, outputs, credentials, and
  provider identity.
- Scope and risk are re-evaluated immediately before execution.
- A material change invalidates prior approval.
- Discovery and execution must occur in the same selected environment.
- Launch is not success; exit status, parsing, and completion criteria decide.
- Findings remain candidates until supported by validation evidence.
- Consequential execution fails closed when policy, audit, or mandatory evidence
  services are unavailable.
- AWS or another remote environment cannot introduce a second policy path.

## Coordinated disclosure

1. Reporter submits details privately.
2. Maintainers reproduce and assess impact.
3. A fix and regression test are developed.
4. Affected users receive mitigation guidance.
5. The fix and advisory are published before coordinated public detail.
