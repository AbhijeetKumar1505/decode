# Contributing to Decode

Decode welcomes focused code, documentation, test, adapter, and research contributions. Security and audit invariants take precedence over convenience.

## Start here

1. Read [AGENTS.md](AGENTS.md), the [documentation hub](docs/README.md), the
   [build plan](docs/BUILD_PLAN.md), and the
   [continuation ledger](docs/CONTINUATION.md).
2. Create a Python 3.11+ virtual environment and install the project dependencies.
3. Copy `.env.example` to `.env` only when a provider-backed test is needed. Unit tests must not require live model APIs or security tools.
4. Inspect `git status --short` and preserve unrelated changes.
5. Confirm the owning phase and maturity label before changing a contract.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
ruff check .
python -m pytest tests/
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

## Configuration

Choose one provider and set its credential:

```dotenv
DECODE_PROVIDER=openrouter
OPENROUTER_API_KEY=replace_me
DECODE_MODEL=z-ai/glm-5.2:free
```

OpenAI uses `OPENAI_API_KEY` and optional `OPENAI_MODEL`; Anthropic uses `ANTHROPIC_API_KEY` and optional `ANTHROPIC_MODEL`. Never commit `.env`, target data, credentials, generated audit data, or deployment-specific registries.

## Development rules

- Target Python 3.11 or newer and type every function signature.
- Keep the execution kernel domain-neutral and tool-agnostic.
- Workflows own procedure; skills and prompts provide guidance only.
- The Core Brain owns strategy and cannot execute; the Active Brain owns one
  bounded node and cannot expand authority.
- Capabilities describe stable operations; tools are replaceable mechanisms.
- Providers own environment-specific discovery and execution. Never discover on
  the host and silently execute in WSL, Docker, SSH, or another environment.
- Exact resolved actions must cross `ExecutionCoordinator` immediately before
  execution.
- Provider adapters prefer validated argument vectors; process transport does
  not decide authorization or success.
- Use legal synthetic, non-routable, or explicitly controlled targets in examples and tests.
- Do not install missing security tools automatically.
- Do not describe planned services as implemented.

## Adding or changing a playbook

Do not add per-tool Python wrapper skills or a hardcoded Kali catalog. A
repeatable method is a markdown playbook in `src/decode/skills/playbooks/` with
validated frontmatter and bounded instructions. Retrieving a playbook is READ;
every command it proposes is independently resolved, risk-classified, scoped,
approved when required, executed, and evidenced.

Use native host capabilities only for genuinely new OS primitives. Use external
MCP servers or declarative plugin packages for integrations. Never add an
in-process plugin loader or an alternate path around the coordinator. See the
[development guide](docs/DEVELOPMENT_GUIDE.md),
[workflow architecture](docs/WORKFLOWS.md), and
[execution pipeline](docs/EXECUTION_PIPELINE.md).

## Risk behavior

| Risk | Required behavior |
|---|---|
| `READ` | May auto-allow only within scope and data policy |
| `WRITE` | Human approval required; output paths must be in write scope |
| `DESTRUCTIVE` | Denied unless the engagement explicitly enables it; human approval still required |

A material change to target, normalized arguments, provider, credentials,
privileges, side effects, outputs, or risk invalidates prior approval.

## Execution providers

Current provider classes cover local, Docker, WSL, SSH, and MCP, with known
wiring gaps tracked in Phase 0. SSH requires explicit connection configuration.
An executor is not a permission decision and is not always a sandbox. Discovery
and execution must share one provider identity, and new execution features must
remain behind the governance gate.

## Testing

Use pytest and isolate external systems with fixtures or fakes.

Cover normal behavior, invalid and unknown inputs, boundary values, non-zero
process exits, scope and permission denial, output-path policy, provider
identity, missing dependencies, timeout/cancellation, parse failures and partial
output, secret redaction, safe resume, and log/audit/evidence/feedback emission.
Live model APIs and security tools must not be required by unit tests.

Run before submitting:

```bash
ruff check .
python -m pytest tests/
```

## Documentation

Update the canonical contract and continuation ledger when behavior or phase
state changes. Preserve **Current**, **Bridge**, **Target**, **Research**, and
**Deferred** labels. Add an ADR only for a durable architecture decision. Verify
relative Markdown links and repository paths.

## Pull requests and issues

Keep changes focused, describe compatibility and safety effects, include validation results, and never include real secrets or unauthorized target data. Report suspected product vulnerabilities privately as described in [SECURITY.md](SECURITY.md).
