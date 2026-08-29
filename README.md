
# Decode

**Local-first cybersecurity agent — a governed universal tool-use loop**

Decode is an open-source, AI-native cybersecurity agent. You describe an objective in natural language; the agent **discovers the tools installed on your machine**, drives them (and your own scripts) through a **governed execution layer**, and reports back — every action scope-checked, risk-classified, approvable, and audited. There is no hardcoded per-tool wrapper: if a tool is installed, the agent can use it; if it isn't, the agent tells you.

---

## Overview

The bare `decode ❯` prompt is a single governed agent loop. Given a goal (or a plain question), it plans → calls one tool → observes the result → iterates, until the goal is met. Its tools are: **host control** (files, processes, services), **tool discovery** (`list_tools`, a `$PATH` scan), and **`shell_command`** — the general path for running any installed CLI. Nothing bypasses the `ExecutionCoordinator`: reads run freely, writes are gated, destructive actions need explicit approval, and everything is written to an audit trail with hashed evidence.

It is designed for security researchers, penetration testers, students, and defenders — intelligent automation that never replaces human judgment or removes a safety control.

## Features

### Current
| Area | Capability |
|------|-----------|
| **Universal agent loop** | One governed plan → call tool → observe → iterate loop drives the whole session; the bare prompt and `/agent` are the same path |
| **Tool discovery** | `list_tools` scans `$PATH` so the agent finds whatever is installed — no hardcoded tool catalog |
| **Governed shell** | `shell_command` runs any installed CLI (or your scripts) as an argument vector — policy-checked, per-command risk-classified, scoped, audited; missing tools are reported, never auto-installed |
| **Host control** | Governed file read/write/edit/search, process list/kill, service status/control, and stateful command sessions |
| **Safety controls** | Deny-by-default filesystem scope + command policy, permission modes (plan/ask/auto), bound approvals, mandatory telemetry, and protected evidence — nothing bypasses `ExecutionCoordinator` |
| **Permission modes** | `plan` (preview only), `ask` (reads auto, writes/destructive gated), `auto` (reads+writes auto in scope, destructive still gated) |
| **Markdown playbooks** | Author reusable procedures as `SKILL.md` files; the agent reads them as guidance and executes each step via governed `shell_command` — no Python wrapper needed |
| **Provider agnostic** | OpenRouter orchestrator (one key, many models) plus OpenAI and Anthropic adapters; model routing with data-locality policy |
| **Persistent memory** | SQLite (or optional MongoDB) session memory: targets, findings, evidence, chain-of-custody |
| **Evidence & audit** | SHA-256 chain-of-custody, integrity verification, and an append-only audit trail for every governed action |
| **Knowledge graph** | Entity-relationship graph linking threats, techniques, and mitigations; capability → MITRE ATT&CK mapping |

### Roadmap

The verified implementation baseline and prioritized release gates are maintained in [ROADMAP.md](ROADMAP.md). Execution governance, universal capability/tool convergence, planning/recovery/memory, model orchestration, and Kali coverage are in place; the in-tree plugin SDK was built and then **removed** in favor of markdown playbooks and native capabilities. The current direction is the De-code subsystem plan — the task-state spine (Neural Schema, prompt composition, a verification pass, and role→model routing) — described in [docs/SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md).

## Architecture

```
User (natural-language goal or question)
 │
 ▼
┌──────────────────────────────┐
│   CLI / REPL (Typer + Rich)  │
└──────────┬───────────────────┘
           │
┌──────────▼───────────────────────────────────┐
│        Universal Agent Loop                   │
│   run_tool_loop: plan → call → observe → …    │
│   (bare prompt and /agent are the same path)  │
└──────────┬────────────────────────────────────┘
           │  every call
┌──────────▼───────────────────────────────────┐
│           ExecutionCoordinator                │
│  scope allowlist · per-command risk · approval│
│  · audit trail · hashed evidence (fail-closed)│
└──────────┬────────────────────────────────────┘
           │
┌──────────▼───────────────────────────────────┐
│        Governed capabilities                  │
│  list_tools │ shell_command │ file/proc/svc   │
│      │            │                            │
│      ▼            ▼                            │
│  $PATH scan   any installed CLI + your scripts│
│               (+ SKILL.md markdown playbooks) │
└──────────┬────────────────────────────────────┘
           │
┌──────────▼───────────────────┐
│      Persistence Layer       │
│  SQLite / MongoDB            │
│  Knowledge Graph  Evidence   │
└──────────────────────────────┘
```

## Installation

### Prerequisites
- Python 3.11+
- Kali Linux, Debian, or any Linux distribution with security tools
- API key for your chosen LLM provider (OpenRouter, OpenAI, or Anthropic)

### Quick Start

```bash
git clone https://github.com/AbhijeetKumar1505/decode
cd decode

python -m venv venv
source venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env with your API key

decode
```

### Docker

```bash
docker build -t decode -f docker/Dockerfile .
docker run -it --network=host decode
```

## Usage

### Interactive Shell

```bash
decode
```

Just type a goal or a question — it runs through the governed agent loop. Slash
commands cover setup, scope, and direct host operations:

| Command | Description |
|---------|-------------|
| *(type a goal or question)* | Run it through the governed universal agent loop |
| `/agent <goal>` | The same loop, invoked explicitly |
| `/scope [targets]` | Show or set the authorized target allowlist (empty scope denies target execution) |
| `/mode plan\|ask\|auto` | Set the permission mode |
| `/fsscope <read> [write]` | Set the filesystem scope for host operations |
| `/tools [query]` | List installed CLI tools (`list_tools`) |
| `/read <path>`, `/ls`, `/ps`, `/run <cmd>` | Governed host operations (files, processes, commands) |
| `/providers` | Show execution providers and health |
| `/knowledge <query>` | Search the local knowledge graph |
| `/start`, `/session`, `/findings`, `/evidence`, `/target` | Session tracking, findings, and evidence |
| `/resume`, `/clear`, `/help`, `/exit` | Session and shell control |

### CLI Subcommands

| Command | Description |
|---------|-------------|
| `decode` | Launch the interactive agent (add `--resume <id>` or `--continue`) |
| `decode tools [query]` | List command-line tools installed on `$PATH` |
| `decode providers` | List execution providers and their health |
| `decode knowledge <query>` | Search the knowledge base |
| `decode doctor` | Run system health diagnostics |
| `decode bootstrap` | Run the first-startup bootstrap sequence |
| `decode --setup` | Configure provider and API key |

### Examples

Everything is a natural-language goal — the agent discovers the tools it needs and
runs them through the governed loop. Active scanning requires an authorized target
(`/scope`) first.

```text
> what web-scanning tools are installed on this host?

> /scope 10.0.0.5
> scan 10.0.0.5 for open ports and services, then summarize what's exposed

> capture 200 packets on eth0 with tshark and summarize the top talkers

> read /etc/os-release and tell me the distro

> run my ./enum.sh script against the authorized target and explain the output

> what is a SYN scan and when would I use one?   # answered directly, no tool call
```

If a tool the agent wants isn't installed, it reports that (e.g. `command not
found: nuclei`) instead of failing silently — and never installs anything itself.

## Documentation

| Document | Description |
|----------|-------------|
| [Documentation Hub](docs/README.md) | Canonical product, architecture, security, research, and engineering index |
| [Product Constitution](docs/PRODUCT.md) | Vision, mission, principles, constraints, and success metrics |
| [System Architecture](docs/SYSTEM_ARCHITECTURE.md) | The universal agent loop, coordinator, and host control |
| [Execution Pipeline](docs/EXECUTION_PIPELINE.md) | The normative intent → govern → execute → evidence path |
| [Security Model](docs/SECURITY_MODEL.md) | Scope, permissions, secrets, plugins, sandboxes, and confirmations |
| [Host Control](docs/HOST_CONTROL.md) | Governed host capabilities and the `/agent` loop |
| [Architecture Decisions](docs/adr/README.md) | Accepted and research decisions |

## Extending with playbooks

Decode has no per-tool Python wrappers. To package a reusable procedure, write
a **markdown playbook** — a `SKILL.md`-style file with YAML frontmatter and a body
of instructions. The agent surfaces it as a tool, reads the instructions as
guidance, and carries out each step through governed `shell_command` (so every
command is still scope-checked, risk-classified, and audited).

```markdown
---
name: web_recon_playbook
description: Progressive passive-to-active web recon of one HTTP(S) target.
category: web_scanning
risk: READ
tags: [web, recon]
inputs:
  target: { type: string, description: Authorized base URL, required: true }
target_required: true
---

# Web Reconnaissance Playbook
1. Confirm the host responds: `curl -sS -I <target>` (or `httpx` if installed).
2. Fingerprint the stack: `whatweb <target>`.
3. Enumerate content (only if in scope) with an authorized wordlist.
4. If `nuclei` is installed, run default templates and summarize by severity.
```

Drop `.md` files in `decode/skills/playbooks/`, or point
`DECODE_PLAYBOOKS_DIR` at your own directory. See
[decode/skills/playbooks/web_recon.md](decode/skills/playbooks/web_recon.md)
for a complete example.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for details on:
- Writing markdown playbooks
- Code style guide
- Pull request process
- Development setup

## License

MIT License — see [LICENSE](LICENSE).

## Security

For security vulnerabilities, see [SECURITY.md](SECURITY.md).
