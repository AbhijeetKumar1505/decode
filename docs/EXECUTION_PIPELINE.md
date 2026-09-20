# Execution Pipeline

**Status:** Phase 0 execution-truth gate is Current; full v2 kernel is Target

A model proposes a capability. Only the kernel resolves, authorizes, executes,
and classifies it.

```text
workflow node -> strict request validation -> provider/tool resolution
 -> exact resolved action -> scope/side-effect/risk -> bound approval
 -> execution -> process/result classification -> normalized observation
 -> evidence/events/audit/usage -> completion verification
```

The resolved action contains capability, provider, executable/version,
argv/payload, cwd, allowlisted environment, credential references, all scopes,
inputs/outputs, side effects, timeout, idempotency, risk, and evidence policy.
Material change invalidates approval.

Reject unknown/missing/wrong-version fields, ambiguous targets, shell syntax in
vector mode, invalid paths, and unsupported tools. Never ignore model params.

Discovery and execution use one EnvironmentProvider. A Kali-discovered tool
cannot run through Windows local without re-resolution.

Classify side effects, not binary names. Output flags, redirects, downloads,
packages, Git mutations, network writes, and credentials raise risk and must pass
scope.

Launch is not success. Require completed transport/process, successful exit/
protocol status, captured output, parser/observation checks, and completion
criteria. Non-zero is failure unless contract maps it otherwise.

Store raw output by protected reference/hash before normalization. Observation
includes success, category, status, summaries, timing, provider/versions,
warnings, evidence, and outputs.

Only transient read-only idempotent failures auto-retry. Timeout/cancel terminates
children. Consequential/ambiguous work moves to review and is not auto-replayed.

Phase 0 corrections are implemented: completed process status is authoritative;
schemas reject unknown/missing/wrong-type fields; vector shell syntax is denied;
recognized output paths raise risk and cross filesystem scope; system-tool PATH
discovery and execution share provider identity; filtered discovery gets an
expanded exact observation budget; and recognizable CLI/MCP targets cross the
engagement allowlist.

Phase 1 must replace remaining transport-specific behavior with a complete
EnvironmentProvider contract, including provider filesystem paths, cwd/env,
stateful sessions, output declarations, health/version identity, and conformance
tests for local Linux, WSL, Docker, and SSH. Unsupported external output/session
operations currently fail closed.
