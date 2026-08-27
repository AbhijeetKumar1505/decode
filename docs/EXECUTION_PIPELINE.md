# Execution Pipeline

## Purpose

The execution pipeline is the normative path from user intent to an evidence-linked
response. Every tool the universal agent calls — a host operation, a discovery
scan, an installed CLI via `shell_command`, or a markdown playbook — passes the
same authorization and observability gates. Nothing bypasses `ExecutionCoordinator`.

**Status (2026-08-25):** implemented. The bare prompt and `/agent` both run
`UniversalAgent.run_tool_loop`; each tool call is executed through the coordinator
via `HostController` (host capabilities) or `execute_registered_skill` (markdown
playbooks). Per-command risk is resolved before the gate. Raw shell strings from
the model are not a path — only the governed `shell_command` argument vector is.

## Lifecycle

```text
User goal or question
      |
The agent loop proposes ONE tool call (or a final message)
      |
Coordinator request built (action, target, params, risk)
      |
Per-command risk classification (shell_command / host_session)
      |
Scope checks: filesystem scope and target scope
      |
Permission decision (mode + risk) -> allow | approve | deny
      |
User approval when required (bound, expiring)
      |
Execution (argument vector; no shell) via the selected executor
      |
Observe: success, output, structured result
      |
Evidence (hashed), structured log, audit event, feedback
      |
Observation returned to the loop -> next step or final answer
```

## 1. Intent

The user's goal (or question) enters the loop. The model's chosen tool call is a
**proposal**; it grants no permission and is validated by the deterministic
pipeline before anything runs. A plain question is answered by a final message
with no tool call.

## 2. Risk classification

For `shell_command` and `host_session`, `CommandPolicy.classify` types the exact
argument vector as READ / WRITE / DESTRUCTIVE **before** the gate
(`decode/runtime/host_controller.py`), so the capability's WRITE baseline never
under-gates a specific command. A DESTRUCTIVE command may not run under
`shell_command` at all.

## 3. Scope

Two deny-by-default allowlists apply:

- `FilesystemScope` — separate read/write path roots; `..` and symlinks are
  resolved before the decision. Host file/command operations are checked against it.
- Target scope (`ScopePolicy`) — addresses, CIDRs, hosts, URLs, wildcard domains.
  Empty scope denies target-bearing actions. Scope is checked immediately before
  execution, because plans and resolved targets can change.

## 4. Permission and mode

`PermissionMode` resolves the decision together with the risk:

| Mode | READ | WRITE | DESTRUCTIVE |
|---|---|---|---|
| `plan` | denied (preview only) | denied | denied |
| `ask` (default) | auto | approval | override + approval |
| `auto` | auto | auto (in scope) | override + approval |

The mode can only lower autonomy or auto-allow in scope; it never auto-allows
DESTRUCTIVE.

## 5. Approval

When approval is required, the prompt shows the action, target, material command,
risk, and side effects. A grant is bound to the action, target, normalized
arguments, executor family, risk, and expiry; a material change or expiry
invalidates it before execution. Credential values are redacted in prompts and logs.

## 6. Execution

Commands run as an **argument vector** — never through a shell (`shell=True` is
never used), so pipes and redirection do not execute. A missing tool returns
`command not found` rather than crashing, and is never auto-installed. Remote and
container executors enforce the same policy; they are not independent authorities.

## 7. Validation and evidence

The observation records success, exit code, stdout/stderr, and duration. Raw
output is written to a protected evidence store (exclusive creation, restricted
permissions, stable id, SHA-256 hash, byte length, immutable after registration)
**before** terminal telemetry. Operational records, logs, and audit events carry
the reference, not the raw bytes.

## 8. Mandatory observability

Every terminal outcome — success, failure, denial, approval failure, timeout,
cancellation — produces a structured execution log, an audit event
(`tool_execution` for executed actions, a rejection event for pre-execution
denials), and execution feedback. If mandatory audit or evidence capture fails, a
consequential action fails closed and does not expose the raw result.

### Audit event (shape)

```json
{ "event": "tool_execution", "tool": "shell_command", "target": "authorized-target", "risk": "WRITE", "approved": true }
```

## Failure and retry

| Failure | Default behavior |
|---|---|
| Invalid input or out-of-scope | Deny without retry |
| Permission denied | Stop and audit |
| Tool not installed | Report `command not found`; never install |
| Transient provider error | Bounded retry only if the operation is safe |
| Timeout | Preserve partial output; inspect before retry |
| Persistence/audit failure | Fail closed for consequential actions |
| Cancellation | Propagate and record the last known state |

Retries never silently change the command, target, executor, or risk.
