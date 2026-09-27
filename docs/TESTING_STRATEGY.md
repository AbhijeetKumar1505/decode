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

## Phase 1 provider conformance bridge

The default suite uses offline fakes for Docker success, non-zero exit, request
timeout, malformed wait status, API error, start-failure cleanup, missing image
without auto-pull, and a missing SDK. Only a
timeout is labeled timed out; API and malformed-status failures remain failures
with their available raw output. Local process tests run on both Windows and
Kali Linux.

Live transport checks are explicit opt-ins in `tests/test_execution.py`:

- On Windows, set `DECODE_RUN_WSL_CONFORMANCE=1` to check success, non-zero
  exit, and a missing command in `wsl/kali-linux`.
- Set `DECODE_RUN_DOCKER_CONFORMANCE=1` and
  `DECODE_DOCKER_CONFORMANCE_IMAGE` to an already-present image containing
  `/bin/sh`. The test inspects the image first and never pulls it. It checks
  success, non-zero exit, missing command, missing image, and no leaked
  containers or image pulls. A reachable daemon is required; an unavailable
  daemon is not counted as a pass.

On the current host, `decode-conformance:local` was built from the explicitly
pulled official `busybox:1.38` base. It is a local Docker artifact, not a
repository file or a portable release image. Pulling a base on another host
requires separate authorization.

Governed task lifecycle checks are in `tests/test_agent_loop.py`. The local
test runs by default. On Windows, `DECODE_RUN_WSL_CONFORMANCE=1` enables the
live `wsl/kali-linux` task; `DECODE_GOVERNED_DOCKER_IMAGE` enables the Docker
task using a cached image with GNU discovery utilities. Each checks governed
tool discovery, command execution, SQLite checkpoints, protected evidence
hash, structured log, audit, feedback, and no automatic action replay on
resume. The Docker process tests separately use
`DECODE_DOCKER_CONFORMANCE_IMAGE`. These tests do not attest to every Linux
distribution or arbitrary CLI side effect.
