# Host Control

## Status

Implemented (foundation): general OS operations are first-class, governed
capabilities. The agent can read/write/edit/search files, list/kill processes,
query/control services, and run policy-checked commands — through the same
scope, risk, approval, audit, and evidence backbone as every security
capability. This makes Decode a general host agent with pentesting built in,
rather than a wrapper around a fixed set of security tools.

## Why it is inbuilt, not a plugin

General system operations already exist on the host; they are core to being a
useful agent. So they ship as **inbuilt capabilities**, never as plugins. There
is no in-tree plugin loader (it was removed); repeatable procedures are added as
markdown playbooks, and *plugins* are reserved for a planned, isolated
external-integration surface ([Extensions and Plugins](PLUGIN_MANIFEST.md)). Core
host and security operations are never delivered as plugins.

## Capability family

| Capability | Risk | Notes |
|---|---|---|
| `file_read`, `file_list`, `file_search` | READ | Within the authorized filesystem scope |
| `file_write`, `file_edit`, `file_fetch` | WRITE | Within the writable scope |
| `process_list` | READ | via `psutil` |
| `process_kill` | DESTRUCTIVE | Terminate by PID |
| `service_status` | READ | `systemctl is-active` |
| `service_control` | DESTRUCTIVE | start/stop/restart |
| `shell_command` | WRITE (per-command risk resolved) | argv-only, no shell string |
| `host_session` | WRITE | Stateful command sequence (shared cwd/env), recorded transcript |

These are `kind="internal"` capabilities owned by `HostAgent`
(`decode/agents/host.py`) and executed through the governed
`decode/hostcontrol/` operations. They are **not** tool-discovery gated.

## Governance

Two policies bound host control, both **deny-by-default** and checked
immediately before execution (`decode/hostcontrol/policy.py`):

- **`FilesystemScope`** — separate read and write root allowlists. Paths are
  resolved before the check, so `..` traversal and symlinks cannot escape.
- **`CommandPolicy`** — binary allow/deny plus an argument-sensitive risk
  classifier. For `shell_command`, the per-command risk (READ/WRITE/DESTRUCTIVE)
  is resolved **before** the gate (`decode/runtime/host_controller.py`), so a
  destructive command never runs under a WRITE approval.

The offline credential audit and every host op preserve the standard invariants:
governed coordinator, scope + risk gate, bound approval, audit event, and hashed
evidence. Nothing bypasses `ExecutionCoordinator`.

## Permission modes

A Claude-Code-style autonomy dial (`PermissionMode`), layered on top of the risk
gate — it can only lower autonomy or auto-allow in scope, **never** auto-allow
DESTRUCTIVE:

| Mode | READ | WRITE | DESTRUCTIVE |
|---|---|---|---|
| `plan` | denied (preview only) | denied | denied |
| `ask` (default) | auto (in scope) | approval | override + approval |
| `auto` | auto | auto (in scope) | override + approval |

## Hooks

`ExecutionCoordinator` accepts an optional `HookRegistry`
(`decode/hostcontrol/hooks.py`). Pre-execution hooks may **veto** a call
(fail-closed); post hooks observe. A hook can never grant permission.

## Using it

REPL commands (`decode`):

- `! <command>` — **shell mode**: run a command directly through the governed
  `shell_command` capability (e.g. `! nmap -sV 10.0.0.5`). Same gate as everything
  else — scope, per-command risk, approval, audit. The running command is shown
  with a live indicator.
- `/read <path>`, `/ls [path]`, `/ps`, `/run <command>` — direct governed ops
- `/fsscope <read_root> [write_root]` — authorize filesystem paths
- `/mode plan|ask|auto` — set the permission mode
- `/model [id]` — list models (with TPM/RPS) or switch the active one
- `/agent <goal>` — bounded **tool-use loop**: the model plans, calls tools one at
  a time, observes each governed result, and iterates. Its first-person reasoning
  (`thought`) and each running step are streamed live
  (`decode/runtime/agent_loop.py`, `UniversalAgent.run_tool_loop`).

Inside the loop, `shell_command` is the general path: the model runs **any**
installed CLI by generating its command line (`{"command": "nmap -sV 10.0.0.5"}`
or a pre-split `{"argv": [...]}`). A tool that is not installed is reported
(`command not found`), never auto-installed.

### sudo and privileged commands

A leading `sudo` is privilege escalation: `CommandPolicy` classifies the *wrapped*
command and never ranks a `sudo` command below WRITE (so `sudo apt install` needs
approval and `sudo rm -rf` is DESTRUCTIVE and blocked via `shell_command`). In
shell mode (`! sudo ...`) the CLI prompts for your sudo password with hidden
input; it is fed to `sudo -S` over stdin and is **never** echoed, logged, stored
as evidence, or sent to the model — it travels in the execution context, not in
audited params.

Programmatic: `HostController` (`decode/runtime/host_controller.py`) runs a
single host capability through the coordinator; `ToolUseLoop`
(`decode/runtime/agent_loop.py`) drives the multi-step loop over any tool set.
