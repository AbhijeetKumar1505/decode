# Testing Strategy

Prove behavior, invariants, failure truth, portability, resume, workflow
completion, evidence integrity, and accounting without live targets/models.

Layers: unit contracts; components; coordinator/provider/storage integration;
security/property/fuzz; Linux/WSL/Docker conformance; controlled labs;
architecture evaluations; CLI/API end-to-end lifecycle.

## Phase 0 regressions

- exit 1 is failed observation/UI;
- unknown tool params rejected;
- vector shell metacharacters rejected;
- output flags are WRITE and destination-scoped;
- discovery/execution provider matches;
- exact discovery reaches model;
- secrets absent from outputs/audit/log metadata;
- denials do not auto-retry.

Workflow tests cover schema/cycles/dependencies, ready nodes, gates, human pause,
persistence/resume fencing, graph version, approval invalidation, idempotency,
conflicts, criteria.

Brain/model tests use deterministic fakes for authority, escalation, malformed
output, abstention, provenance, routing filters, fallback, no repeated action.

Security tests use seeded positives/negatives and labs for candidate/confirmed
precision/recall, coverage, validation, scope/rate, remediation/regression.

Migration tests cover clean install, upgrade, interruption, rollback, old resume,
events, conflicts, backup/restore, retention/deletion.

Release runs configured lint/type/test plus security, links, migrations,
conformance. Default suite is deterministic/offline; labs are explicitly gated.

Native Windows is a required portability gate for filesystem permissions,
SQLite lifecycle, runtime-path isolation, CLI output, and host behavior that does
not require Linux tooling. The current checkout uses the ignored `wenv` virtual
environment. Linux-sensitive behavior is independently rerun in Kali WSL; a
native Windows pass does not replace that provider gate.
