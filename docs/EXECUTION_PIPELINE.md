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

Phase 1 now has a typed EnvironmentProvider identity/capability/filesystem-mode
contract and lexical host-to-provider path resolution. Local paths are shared;
WSL, Docker, and SSH require an explicit mapping; MCP has no host filesystem.
A typed execution context now binds supported cwd/environment/output declarations
to each transport. Classified external output paths cross host filesystem scope,
map through an explicit writable provider mapping, are rewritten only in their
known argv positions, and are included in the approval-bound action. Unmapped or
read-only outputs fail closed. Provider sessions now bind immutable session and
provider identity to mapped cwd/environment context. Every command is separately
policy/scope checked and governed; cwd transitions are verified in the selected
provider before state changes. Local, WSL, and SSH support this context-persistent
contract. Docker and MCP sessions remain fail-closed. Resolved tool/version,
side-effect, timeout/idempotency/evidence metadata and broader local Linux, WSL,
Docker, and SSH conformance remain.

The Phase 1 Bridge now attaches a strict, versioned ResolvedAction to governed
host CLI commands and provider session commands. It binds capability, selected
provider, tool name, exact argv, target, cwd, declared host/provider outputs,
known side effects, actual timeout, idempotency status, protected raw evidence
policy, and raw-only parser policy to the approval digest. The selected
capability's schema versions populate ExecutionIdentity. The coordinator
checks action/request coherence and rechecks the digest immediately before
execution. Approval receives a redacted action; audit, logs, and feedback receive
a compact action summary without argv or filesystem paths.

Awaited executable preparation finishes before the coordinator's final action,
stage-envelope, and policy checks. The earlier of approval-grant and request
expiry is checked before every operation, including operations without a
preparation hook. Host commands then synchronously revalidate scope, command
policy/risk, provider identity/mappings, and session context before launch.
Coordinator cancellation preserves the recorded result and provider; both
Active stage adapters retain cancelled request IDs without retry.

Tool version is empty when unverified. Exact governed `list_tools` lookup can
fingerprint executable content in the selected provider. Governed CLI and
session actions now replace executable names with resolved
absolute paths, bind each path and SHA-256 to approval, and re-hash immediately
before launch. Local sessions use their captured PATH, bind an environment
hash and cwd to approval, and reject a changed executable or session context.
`sudo` binds both execution stages. Discovery queries PATH only,
not the full environment; the digest is content identity, not a semantic
version. Inputs are typed but no general CLI input inference is claimed. Side
effects without a known classification are
marked unknown and require at least WRITE risk; provider session state changes
also require WRITE risk. Other capability families still use the compatible
ExecutionRequest path and await full resolved-action migration.

Docker process-result conformance now distinguishes request timeouts from API
errors and malformed wait responses. Non-zero exits remain failures; available
stdout/stderr survive timeout or malformed-status classification, and disposable
containers are removed after every created outcome, including start failure.
The provider uses explicit create/start so a missing image cannot trigger the
Docker SDK's implicit pull. Live process-outcome conformance passed with a
local test image. Governed task lifecycle conformance now passes with a cached
GNU-compatible Debian image as well as direct local Linux and Kali WSL: task
actions are checkpointed before execution, observations after execution, and
completion at the final boundary. Checkpoints omit raw command parameters,
thoughts, and tool-output data; protected evidence remains referenced by hash.
Resume requires the same task/session and a balanced action/observation history;
an unresolved action is not replayed automatically. A failed checkpoint stops
subsequent execution. Broad provider PATH scans retry after excluding missing
provider-side directories, which handles stale inherited Windows PATH entries
in WSL; a persistent scan failure retains partial raw output and fails closed.
Minimal images without the current GNU discovery utilities remain unsupported.
