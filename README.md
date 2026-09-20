# De-code

De-code is a Linux-first, local-first runtime for engineering work and
explicitly authorized security operations. Models provide cognition; the
runtime provides procedure, authority, state, evidence, verification, and
resource control.

> Model = cognition. Runtime = authority. Workflow = procedure. Evidence = truth.

De-code is designed for engineers, security researchers, incident responders,
and authorized red, blue, and purple teams. It is not an unrestricted
exploitation system: scope, permissions, approvals, evidence capture, and audit
logging are enforced by the runtime rather than delegated to a model.

> Only use Decode against systems, networks, files, and accounts that you own
> or are explicitly authorized to test.

## Project status

De-code is moving from its governed Python universal-agent baseline to the v2
workflow runtime. Documentation uses five maturity labels:

- **Current** — present in source and supported by tests.
- **Bridge** — a deliberate migration implementation.
- **Target** — accepted v2 design that is not complete.
- **Research** — a hypothesis that still needs evaluation.
- **Deferred** — outside the active build phase.

The current baseline includes the Python CLI/TUI, universal tool loop,
coordinator and governance, host capabilities, execution providers, SQLite,
evidence/audit foundations, task/DAG primitives, model adapters, and MCP.
Markdown workflows and the combined universal loop are Bridge components. The
Core/Active Brain split, workflow v2 schema, runtime FSM, UTOS, local API,
TypeScript CLI, and AWS deployment are Target or Deferred work.

Use the [canonical build plan](docs/BUILD_PLAN.md) for sequence and the
[continuation ledger](docs/CONTINUATION.md) to resume implementation safely.

## What Decode does

The interactive agent uses one governed loop:

```text
user goal
  -> plan
  -> select one capability
  -> governance and scope checks
  -> approval when required
  -> execute
  -> capture evidence and telemetry
  -> observe and continue
```

The model can propose an action, but it cannot grant itself permission. Every
consequential action is routed through `ExecutionCoordinator`, which applies:

- Target and filesystem allowlists.
- Per-command risk classification.
- Permission modes: `plan`, `ask`, and `auto`.
- Human approval for writes and destructive operations.
- Mandatory audit, structured logging, feedback, and protected evidence.
- Secret redaction and fail-closed behavior when required safety services fail.

## Main capabilities

| Area | What is included |
| --- | --- |
| Universal agent | Natural-language questions and goals through a bounded plan-call-observe loop |
| Tool discovery | Finds installed commands on `$PATH`; it never auto-installs missing tools |
| Governed commands | Runs installed CLIs and scripts through `shell_command` |
| Host control | Governed file read/write/edit/search, process inspection, service operations, and persistent command sessions |
| Security scope | Authorized hosts, URLs, CIDRs, domains, and filesystem roots |
| Execution providers | Local, Docker, WSL, SSH, and MCP provider integrations |
| MCP server | Exposes the governed host capabilities to MCP-compatible and HTTP clients over a local port or stdio; also consumes external MCP servers |
| Sessions | Automatic session creation on the first task, human-readable `dc_…` ids, resume/continue, and per-session transcripts |
| Playbooks | Markdown procedures that provide reusable guidance without Python tool wrappers |
| Persistence | SQLite by default, with optional MongoDB operational storage |
| Evidence and audit | Protected evidence references, SHA-256 integrity checks, append-oriented audit records |
| Knowledge and memory | Local project/session memory and a security knowledge graph |

## Architecture

```text
User / CLI / future API
          |
Core Brain: strategy, workflow, DAG, budget, stop
          |
Workflow Engine: phases, dependencies, gates, checkpoints
          |
Active Brain: one bounded operation, context, recovery
          |
Execution Kernel
  capability -> environment -> policy/scope/risk -> approval
          |
Provider: local / WSL / Docker / SSH / MCP
          |
Verification -> Evidence -> Findings -> Memory / Audit / Usage
```

Core Brain and Active Brain are Target architecture. Today, the universal agent
loop combines parts of those responsibilities and must remain bounded by the
same execution coordinator. Workflows own procedure, capabilities describe
stable operations, providers own environment-specific discovery and execution,
and tools remain replaceable mechanisms.

The source is organized under `src/decode/`:

| Package | Responsibility |
| --- | --- |
| `app/` | CLI, configuration, and interactive TUI |
| `agents/` | Agent abstractions and `HostAgent` |
| `capabilities/` | Typed capability definitions and resolution |
| `governance/` | Scope and pre-execution policy |
| `hostcontrol/` | Filesystem, command, process, service, and session operations |
| `runtime/` | Agent loop, coordinator, and host controller |
| `execution/` | Local, Docker, WSL, SSH, and MCP providers |
| `mcp/` | Decode's own MCP/HTTP server: exposes the governed capabilities to MCP and HTTP clients |
| `persistence/` | SQLite/Mongo stores, `SessionManager`, and protected evidence |
| `observability/` | Audit, logging, feedback, and replay records |
| `skills/` | Markdown playbook discovery and registration |
| `models/`, `memory/`, `knowledge/` | Model routing, memory, and security knowledge |

## Installation

### Prerequisites

- Python 3.11 or newer.
- Git.
- Linux, macOS, Windows, or Windows with WSL.
- Credentials for one supported model provider:
  - OpenRouter (default)
  - OpenAI
  - Anthropic
  - Mistral (`MISTRAL_API_KEY`)
  - AWS Bedrock (standard AWS credentials + region; needs the `decode[bedrock]` extra)
- Any security tools you want Decode to drive, such as `nmap`, `nuclei`,
  `whatweb`, or `tshark`. These are optional and are not installed by Decode.

On Windows, use WSL for Linux-native security tools and follow the repository's
WSL testing guidance.

### Install from a clone

```bash
git clone https://github.com/AbhijeetKumar1505/decode.git
cd decode

python -m venv .venv
```

Activate the environment:

```bash
# Linux or macOS
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Install Decode in editable mode:

```bash
python -m pip install --upgrade pip
python -m pip install -e .
```

For development and tests:

```bash
python -m pip install ruff pytest mongomock
```

Optional extras enable the MCP/HTTP server transports (see
[docs/MCP_SERVER.md](docs/MCP_SERVER.md)):

```bash
python -m pip install -e '.[server]'   # FastAPI + uvicorn — localhost HTTP transport
python -m pip install -e '.[mcp]'      # MCP SDK — native MCP over stdio and HTTP
```

The project uses `pyproject.toml` as its packaging and dependency definition.
`requirements.txt` is retained as a small editable-install convenience file.

### Docker

Build the image:

```bash
docker build -t decode -f docker/Dockerfile .
```

Run the interactive client:

```bash
docker run --rm -it --network=host decode
```

Review the container and network policy before using Docker for sensitive or
active work. Docker is an execution provider, not an automatic authorization
grant.

## First-time setup

### 1. Configure a model provider

Copy the example environment file:

```bash
cp .env.example .env
```

Then set one provider and its API key. For example:

```dotenv
DECODE_PROVIDER=openrouter
OPENROUTER_API_KEY=your-key-here
DECODE_MODEL=openrouter/free
```

Alternative providers use:

```dotenv
DECODE_PROVIDER=openai
OPENAI_API_KEY=your-key-here
```

or:

```dotenv
DECODE_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-key-here
```

Never commit `.env`, API keys, credentials, or raw evidence.

### 2. Check the installation

```bash
python -m decode --help
python -m decode --doctor
```

The installed console script is equivalent:

```bash
decode --doctor
```

`--doctor` checks the local environment and available dependencies. It does not
install missing security tools.

### 3. Understand runtime storage

Runtime state is kept outside the repository by default:

```text
~/.decode/
  data/       SQLite database and local model-related state
  audit/      Audit records
  evidence/   Protected execution evidence
  feedback/   Execution and decision feedback
  logs/       Structured logs
  profiles/   Local profiles
  sessions/   REPL conversation snapshots
```

Set a different root when required:

```bash
DECODE_HOME=/path/to/decode-state decode
```

Individual paths can also be configured with variables such as `LOGS_PATH`,
`AUDIT_PATH`, `EVIDENCE_PATH`, `MEMORY_PATH`, and `PROFILES_PATH`.

## Basic workflow

### 1. Start Decode

```bash
decode
```

A session is created automatically on your first task — there is no `/start`
step. Sessions get a human-readable id such as `dc_20260911_8f31abcd`, and each
one keeps its own conversation transcript. Inside the REPL:

```text
> /status      show the active session (id, goal, target, model, mode, findings)
> /sessions    list recent sessions
> /continue    resume the most recent session
> /reset       close the session and start fresh
```

You can also resume from the shell:

```bash
decode --resume SESSION_ID
decode --continue
```

### 2. Choose a permission mode

Start conservatively:

```text
> /mode ask
```

The modes are:

| Mode | Behavior |
| --- | --- |
| `plan` | Preview work without executing actions |
| `ask` | Reads may run in scope; writes require approval |
| `auto` | Reads and in-scope writes may run automatically; destructive actions still require explicit controls and approval |

### 3. Set target scope before active work

Use only targets you are authorized to test. A synthetic documentation example
is:

```text
> /scope 192.0.2.10
```

An empty target scope denies target execution. Scope is checked again
immediately before execution; a model, prompt, playbook, or tool output cannot
expand it.

### 4. Set filesystem scope

Authorize a read root and, if needed, a separate write root:

```text
> /fsscope /home/research/lab /home/research/lab/output
```

On Windows, use an absolute Windows path or operate through WSL with the
corresponding mounted path.

### 5. Discover installed tools

```text
> /tools
> /tools nmap
```

Decode reports missing commands instead of installing them automatically.

### 6. Ask for a bounded task

Natural-language input and `/agent` use the same governed loop:

```text
> /agent inspect the authorized lab host and summarize its exposed services
```

For a plain question, no tool call is necessary:

```text
> explain the difference between passive and active reconnaissance
```

### 7. Inspect the result and evidence

Useful commands include:

```text
> /session
> /findings
> /evidence
> /providers
> /knowledge authentication logging
```

Execution output is preserved as protected evidence and linked from the
operational session record. Audit and log files contain references and
redacted metadata rather than secrets.

## Interactive commands

| Command | Purpose |
| --- | --- |
| `/agent <goal>` | Run an explicit governed agent task |
| `/scope [targets]` | Show or set authorized target scope |
| `/mode plan\|ask\|auto` | Show or set permission mode |
| `/fsscope <read> [write]` | Show or set filesystem scope |
| `/tools [query]` | Discover installed command-line tools |
| `/read <path>` | Read a file within filesystem scope |
| `/ls [path]` | List a directory within filesystem scope |
| `/ps` | List processes |
| `/run <command>` | Execute a governed command |
| `! <command>` | Run a command through governed shell mode |
| `/providers` | Show execution providers and health |
| `/knowledge <query>` | Search the local knowledge graph |
| `/status` | Show the active session (id, goal, target, model, mode, findings, token/cost usage) |
| `/cost` | Show session token usage and estimated cost |
| `/trace` | Show the session's agent-run trace (task class, steps, tokens, cost) |
| `/sessions` | List recent sessions |
| `/continue` | Resume the most recent session |
| `/resume <id>` | Resume a specific saved session |
| `/checkpoint` | Save a manual checkpoint (transcript + TaskState) without closing |
| `/reset` | Close the active session and clear context |
| `/session`, `/target`, `/start` | Show session context, set the target, or start one explicitly (a session also starts automatically on the first task) |
| `/findings`, `/evidence` | Review findings and evidence references |
| `/model [id\|refresh]` | Fetch all OpenRouter catalogue models, select one, or refresh the catalogue |
| `/clear` | Clear the current interactive context |
| `/version` | Show the installed Decode version |
| `/help` | Show command help |
| `/exit` | Exit the REPL |

Use `/help <command>` for command-specific details.
For scripts, `decode models --json` returns the complete live OpenRouter
catalogue with context, capability, and pricing metadata.
OpenRouter defaults to `openrouter/free`, enables reasoning on chat requests, and
preserves returned `reasoning_details` across follow-up and tool-use turns.

## MCP server

Decode can expose its governed host capabilities to MCP-compatible clients and
to plain HTTP clients, and can consume external MCP servers as tools. Every call
still routes through `ExecutionCoordinator`, so scope, permission mode, approval,
audit, and evidence are unchanged — the server is a transport, not a new
execution path.

Install the transport you need, then start the server (local bind, `ask` mode by
default):

```bash
python -m pip install -e '.[server]'    # HTTP transport (FastAPI + uvicorn)
python -m pip install -e '.[mcp]'       # native MCP (stdio + HTTP), via the MCP SDK

decode mcp start                        # HTTP on http://127.0.0.1:8765
decode mcp start --transport stdio      # native MCP over stdio
decode mcp status                       # recorded endpoint + health
decode mcp stop
```

With `decode[server]` the HTTP transport serves `GET /health`, `GET /tools`, and
`POST /tools/{name}`. With `decode[mcp]` it additionally mounts a native MCP
streamable-HTTP endpoint at `/mcp`, and `--transport stdio` speaks MCP over
stdio for clients that launch a subprocess. Register external MCP servers with
`decode mcp add`. See [docs/MCP_SERVER.md](docs/MCP_SERVER.md) for the full
reference, transports, governance modes, and security notes.

## Usage examples

### Host inspection

```text
> /fsscope /etc
> /read /etc/os-release
> /ps
```

### Tool-assisted work against an authorized lab target

```text
> /scope 192.0.2.10
> /mode ask
> /agent use an installed port scanner against 192.0.2.10 and summarize the results
```

### Run an installed script

```text
> /scope 192.0.2.10
> /fsscope /home/research/scripts /home/research/results
> /agent run /home/research/scripts/enum.sh against the authorized lab target and explain the output
```

### Direct command mode

```text
> ! nmap -sV 192.0.2.10
```

Direct mode still passes through command policy, target scope, approval,
evidence capture, and audit. It is not an unrestricted shell escape.

## Markdown playbooks

Reusable procedures are authored as Markdown, not Python wrappers. A playbook
contains YAML frontmatter and instructions that the agent follows. Each command
from the procedure is still executed through the governed command capability.

Playbooks guide method; they do not authorize targets, select providers,
determine process success, persist state, or confirm findings.

Playbooks are discovered from:

```text
src/decode/skills/playbooks/
```

or from directories listed in `DECODE_PLAYBOOKS_DIR`.

Example:

```markdown
---
name: web_recon_playbook
description: Progressive reconnaissance of one authorized web target.
category: web_scanning
risk: READ
tags: [web, recon]
target_required: true
---

# Web reconnaissance

1. Confirm the authorized host responds.
2. Fingerprint the web stack.
3. Enumerate content only when it remains in scope.
4. Summarize findings with evidence references.
```

See [the bundled web reconnaissance playbook](src/decode/skills/playbooks/web_recon.md)
and [the development guide](docs/DEVELOPMENT_GUIDE.md) for the complete format.

## Workflow Bridge

For work that needs enforced phase order, evidence gates, human checkpoints, and
safe resume, a playbook can also declare a workflow DAG:

```text
decode workflow list
decode workflow show engineering-delivery
decode workflow run engineering-delivery --goal "Implement the approved change" --write-root .
decode workflow resume <session-id> --approve approve_plan
```

Bundled workflows cover engineering delivery, source-first security audits,
authorized red-team assessments, blue-team incident response, and purple-team
control validation. This implementation is a **Bridge**: the Target is a
versioned, validated YAML workflow schema with a DAG scheduler, runtime FSM,
evidence gates, conflict-aware concurrency, and safe resume. Models remain
bounded stage workers, and every action still crosses the normal scope,
permission, evidence, and audit gate. See
[workflow architecture](docs/WORKFLOWS.md).

## Environment discovery and browsing

De-code does not rely on a hardcoded Kali tool list. It discovers executables in
the selected environment and must execute them through that same provider. A
native Linux host, Kali WSL distribution, and Docker container may each have a
different PATH and dependency set.

An installed browser or `curl` is only a binary; it is not automatically a
governed semantic browser or search provider. Browsing, search, authenticated
sessions, downloads, output-path scope, and evidence capture require explicit
capability contracts. Phase 0 now binds system-tool discovery and execution to
one provider, rejects loose parameters and shell syntax, classifies explicit
outputs, and scope-checks recognizable network targets. Semantic browsing/search
appears only when a configured provider advertises it. External-provider file
outputs and stateful sessions remain fail-closed until Phase 1 supplies those
provider contracts.

## Configuration reference

Common environment variables:

| Variable | Purpose |
| --- | --- |
| `DECODE_PROVIDER` | `openrouter`, `openai`, `anthropic`, `mistral`, or `bedrock` |
| `DECODE_MODEL` | Default model identifier |
| `OPENROUTER_API_KEY` | OpenRouter credential |
| `OPENAI_API_KEY` | OpenAI credential |
| `ANTHROPIC_API_KEY` | Anthropic credential |
| `MISTRAL_API_KEY` | Mistral credential |
| `AWS_ACCESS_KEY_ID` / `AWS_REGION` | AWS Bedrock credentials/region (with the `decode[bedrock]` extra) |
| `DECODE_EXECUTOR` | Execution provider: `local`, `wsl/<distribution>`, or another configured provider |
| `DECODE_HOME` | Root directory for runtime state |
| `MEMORY_PATH` | Memory/model state path |
| `LOGS_PATH` | Structured log path |
| `AUDIT_PATH` | Audit record path |
| `EVIDENCE_PATH` | Protected evidence path |
| `FEEDBACK_PATH` | Feedback path |
| `PROFILES_PATH` | Profile path |
| `DECODE_PLAYBOOKS_DIR` | Additional playbook directories |
| `MONGODB_URI` | Optional MongoDB connection |
| `MONGODB_DB` | MongoDB database name, default `decode` |

SQLite remains the default operational store. MongoDB is optional and does not
change scope, permission, approval, audit, or evidence requirements.

## Development

Install development dependencies:

```bash
python -m pip install -e .
python -m pip install ruff pytest mongomock
```

Run the required checks:

```bash
ruff check .
python -m pytest tests/
```

For Windows, run the suite in WSL when testing Linux command behavior:

```bash
wsl -- python -m pytest tests/
```

Read [docs/README.md](docs/README.md) for the canonical documentation index,
[docs/SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md) for architecture,
[docs/HOST_CONTROL.md](docs/HOST_CONTROL.md) for host operations, and
[docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md) for trust and authorization
rules.

## Troubleshooting

### `command not found`

The requested CLI is not installed or is not visible on `$PATH`. Install it
through your operating system's approved process, then restart or re-run
`/tools`. Decode never installs tools automatically.

### Missing provider credential

Run `decode --doctor`, check `DECODE_PROVIDER`, and verify the matching API key
is present in `.env` or the process environment. Do not paste keys into chat,
prompts, playbooks, or source files.

### Scope or approval denial

Review `/scope`, `/fsscope`, and `/mode`. A denial is intentional when the
target or path is not explicitly authorized, the command risk is too high, or
required approval was not provided.

### Runtime files in the repository

Set `DECODE_HOME` to a user-owned state directory and remove only known,
disposable generated files. Do not delete audit or evidence data that may be
needed for an investigation.

## Documentation

- [Documentation hub](docs/README.md)
- [Product constitution](docs/PRODUCT.md)
- [Canonical build plan](docs/BUILD_PLAN.md)
- [Continuation ledger](docs/CONTINUATION.md)
- [System architecture](docs/SYSTEM_ARCHITECTURE.md)
- [Core Brain and Active Brain](docs/BRAIN_ARCHITECTURE.md)
- [Repository migration map](docs/REPOSITORY_STRUCTURE.md)
- [Workflow architecture](docs/WORKFLOWS.md)
- [UTOS](docs/UTOS.md)
- [Execution pipeline](docs/EXECUTION_PIPELINE.md)
- [Security model](docs/SECURITY_MODEL.md)
- [Host control](docs/HOST_CONTROL.md)
- [MCP server and HTTP endpoint](docs/MCP_SERVER.md)
- [Development guide](docs/DEVELOPMENT_GUIDE.md)
- [Plugin and extension manifest](docs/PLUGIN_MANIFEST.md)
- [Roadmap](ROADMAP.md) · [Pre-AWS engineering roadmap](docs/PRE_AWS_ROADMAP.md)

Source and tests define current behavior. Accepted ADRs define durable
decisions. The build plan defines implementation order. The continuation ledger
defines the exact resumption point.

AWS is **Deferred** until local Linux, Kali WSL, and Docker gates pass and the
user creates the AWS project. Cloud deployment will map stable local contracts;
it will not create a second policy or execution path.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for coding standards, testing,
playbooks, and pull request guidance.

## License and security

Decode is released under the [MIT License](LICENSE). To report a vulnerability,
follow [SECURITY.md](SECURITY.md) and do not disclose sensitive details in a
public issue.
