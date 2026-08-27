# Security Policy

## Intended use

Decode is for education, defensive analysis, research, and security testing of systems the operator owns or has explicit written authorization to assess. It is not an unrestricted exploitation system.

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
| Risk classification | Skills declare `READ`, `WRITE`, or `DESTRUCTIVE` risk |
| Scope policy | Allowlist; empty scope denies target execution |
| Human approval | `WRITE` requires approval; `DESTRUCTIVE` also requires an explicit engagement override |
| Mission governance | `MissionRunner` uses the governance gate before execution |
| Raw model commands | Blocked in the conversational REPL |
| Execution providers | Local, Docker, WSL, configured SSH, and MCP |
| Evidence integrity | SHA-256 and chain-of-custody foundations |
| Observability | Structured log, audit, and feedback services exist |
| Provider keys | Loaded from environment configuration and must never be logged |

## Known limitations

Mission CLI/workflows, registered conversational skills, and the legacy attack chain now share a governed coordinator; direct low-level skill/executor APIs and some domain CLI modules are not yet migrated. Local, WSL, SSH, and MCP execution are not inherently isolated. Plugins are trusted Python code imported in-process. Storage encryption, multi-user authorization, and a network-facing control plane are not implemented.

The P0 work in the [release roadmap](ROADMAP.md) is required before Decode can claim universal pre-execution governance or complete audit coverage. See the canonical [security model](docs/SECURITY_MODEL.md) and [threat model](docs/threat-model.md).

## Coordinated disclosure

1. Reporter submits details privately.
2. Maintainers reproduce and assess impact.
3. A fix and regression test are developed.
4. Affected users receive mitigation guidance.
5. The fix and advisory are published before coordinated public detail.
