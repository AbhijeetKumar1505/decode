# Decode Threat Model

This model covers Decode and its execution environments. The normative controls are defined in [Security Model](SECURITY_MODEL.md); this page records threats and present control maturity.

## Trust boundaries

```text
User and engagement authorization
  -> CLI / REPL input boundary
  -> model provider boundary
  -> kernel, agent, skill, and plugin code boundary
  -> governance and approval boundary
  -> Local / Docker / WSL / SSH / MCP execution boundary
  -> authorized target boundary
  -> persistence, evidence, log, audit, and feedback boundary
```

Local, WSL, SSH, and MCP executors are not automatically sandboxes. Docker isolation depends on daemon, image, network, capability, and mount configuration.

## Assets

| Asset | Sensitivity | Primary concern |
|---|---|---|
| Provider and executor credentials | Critical | Disclosure or misuse |
| Scope and approval records | Critical | Forgery, replay, or ambiguity |
| Target data and evidence | Sensitive | Confidentiality and integrity |
| Tool/model output | Untrusted, potentially sensitive | Injection, poisoning, and leakage |
| Markdown playbooks and native capabilities | Trusted in-tree code, governed at execution | Supply-chain and privilege expansion (future external plugins) |
| Audit and feedback data | Sensitive | Tampering, omission, or secret capture |

## Threats and controls

| Threat | Current controls | Remaining work |
|---|---|---|
| Prompt or tool-output injection | Typed model responses, registered-skill preference, raw model commands blocked, compatibility execution fail-closed, and public execution boundaries inventoried | Typed provider-portable domain adapters; adversarial evaluation |
| Out-of-scope execution | Shared coordinator with immediate pre-execution scope checks, exact-action context, executor-family binding, and public boundary inventories | Continue inventory enforcement as new adapters and entry points are added |
| Approval replay or confused deputy | Approval digest binds action, target, normalized arguments, command, executor, risk, privileges, opaque credential references, and absolute expiry | Durable actor identity and approval-replay ledger |
| Command or argument injection | Typed skill inputs and adapter patterns | Remove raw command compatibility and complete argument-vector migration |
| Secret exposure | Central display/log/error redaction, opaque credential references, protected evidence, and regression tests | Secret-store integration and deployment key management |
| Malicious or vulnerable extension | No in-tree plugin loader (removed); extension is via reviewed markdown playbooks and native capabilities, all governed at execution | A future external-integration plugin surface needs manifest, source pinning, isolation, revocation, and conformance tests before adoption |
| Evidence or memory poisoning | Immutable protected evidence files, SHA-256 references, path ownership checks, and hash verification | Rich verification state and retention/deletion controls |
| Provider compromise or unsafe response | Provider-independent kernel and schema validation | Data-policy-aware routing and systematic fallback tests |
| Session or data theft | Local-first SQLite by default | File permission validation, optional encryption, protected exports, multi-user auth before team mode |
| Telemetry omission | Mandatory coordinator logging, audit, and feedback for every terminal outcome with boundary inventory tests | Extend equivalent guarantees to future distributed and plugin lifecycle paths |

## Security invariants

- Authorization is explicit and target-scoped.
- Empty scope denies target execution.
- Models, prompts, plugins, and tool output cannot grant permission.
- `WRITE` requires human approval.
- `DESTRUCTIVE` requires an explicit engagement override and human approval and otherwise denies.
- Material action changes invalidate approval.
- Missing mandatory governance or audit services stop consequential execution.
- Secrets are never intentionally placed in prompts, logs, audit events, errors, or documentation.

## Assumptions

- The operator has legal authorization for every target.
- The local host and configured executor environments are administered appropriately.
- Provider and remote credentials are least-privilege and protected outside the repository.
- Third-party output is untrusted until validated.

## Out of scope today

Network-facing multi-user control plane, distributed workers, PostgreSQL shared state, Redis event transport, Qdrant retrieval, and isolated third-party plugin execution are not current production features. Their threat models must be completed before adoption.

See [the release roadmap](../ROADMAP.md) for remediation order and [SECURITY.md](../SECURITY.md) for responsible disclosure.
