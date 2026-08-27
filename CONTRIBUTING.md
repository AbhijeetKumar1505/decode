# Contributing to Decode

Decode welcomes focused code, documentation, test, adapter, and research contributions. Security and audit invariants take precedence over convenience.

## Start here

1. Read [AGENTS.md](AGENTS.md), the [documentation hub](docs/README.md), and the canonical document for the subsystem.
2. Create a Python 3.11+ virtual environment and install the project dependencies.
3. Copy `.env.example` to `.env` only when a provider-backed test is needed. Unit tests must not require live model APIs or security tools.
4. Inspect `git status --short` and preserve unrelated changes.

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
- Keep the kernel domain-neutral and tool-agnostic.
- Agents request stable capabilities through `CapabilityRegistry`; they do not name binaries or assemble raw commands.
- Skills validate typed inputs and dependencies, normalize results, and produce required telemetry.
- Provider adapters build argument vectors; executors only transport commands.
- Use legal synthetic, non-routable, or explicitly controlled targets in examples and tests.
- Do not install missing security tools automatically.
- Do not describe planned services as implemented.

## Adding or changing a skill

A `Skill` subclass returns a `SkillSpec` containing a stable name, description, category, risk level, typed input/output schemas, tags, and approval requirement. External-command support must also define or reuse a capability, validate dependency availability, pass through scope and governance, preserve raw output, normalize through a compatible parser, and emit structured log, audit, and feedback records.

Registration is automatic through package discovery. Avoid import-time execution and dependency installation. See [Development Guide](docs/DEVELOPMENT_GUIDE.md), [Tool Registry](docs/TOOL_REGISTRY.md), and [Execution Pipeline](docs/EXECUTION_PIPELINE.md).

## Risk behavior

| Risk | Required behavior |
|---|---|
| `READ` | May auto-allow only within scope and data policy |
| `WRITE` | Human approval required |
| `DESTRUCTIVE` | Denied unless the engagement explicitly enables it; human approval still required |

A material change to target, normalized arguments, executor, credentials, privileges, or risk invalidates prior approval.

## Execution providers

Implemented providers are local, Docker, WSL, SSH, and MCP. SSH requires explicit connection configuration. An executor is not a permission decision and is not always a sandbox. New execution features must remain behind the governance gate and must not introduce direct bypasses.

## Testing

Use pytest and isolate external systems with fixtures or fakes.

```python
import asyncio


def test_skill_spec() -> None:
    skill = MyNewSkill()
    assert skill.spec.name == "my_new_skill"


def test_skill_result() -> None:
    result = asyncio.run(MyNewSkill().execute(target="192.0.2.10"))
    assert "results" in result
```

Cover normal behavior, invalid and boundary inputs, scope/permission denial, missing dependencies, timeout/cancellation, parse failures and partial output, secret redaction, and log/audit/feedback emission. Run before submitting:

```bash
ruff check .
python -m pytest tests/
```

## Documentation

Update the canonical contract when behavior changes. Preserve **implemented**, **partial**, **planned**, and **research** labels. Add an ADR only for a durable architecture decision. Verify relative Markdown links and repository paths.

## Pull requests and issues

Keep changes focused, describe compatibility and safety effects, include validation results, and never include real secrets or unauthorized target data. Report suspected product vulnerabilities privately as described in [SECURITY.md](SECURITY.md).
