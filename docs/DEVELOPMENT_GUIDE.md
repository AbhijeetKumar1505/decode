# Development Guide

## Repository layout

```text
decode/
  agents/          Agent base + HostAgent (governed host capabilities)
  bootstrap/       Startup and host preparation
  capabilities/    Host-capability specs (kind="internal")
  execution/       Local, Docker, WSL, SSH, and MCP providers
  governance/      Scope and pre-execution policy
  hostcontrol/     Filesystem/command policy, operations, sessions, hooks
  kernel/          Context, safety, model provider
  knowledge/       Knowledge graph, retrieval, capability -> ATT&CK map
  memory/          Session, project, and semantic memory
  persistence/     SQLite/Mongo sessions, evidence, and artifacts
  planner/         DAG data types (PlanNode, PlanGraph) — task-state primitives
  reports/         Report renderers
  runtime/         ExecutionCoordinator, HostController, ToolUseLoop
  skills/          SkillRegistry + markdown playbooks (SKILL.md)
  tui/             Rich + prompt_toolkit REPL
  universal_agent.py  The universal agent (run_tool_loop)
tests/             pytest suite
docs/              Product and engineering documentation
examples/          Legal, controlled usage examples
prompts/           Versioned prompt definitions
```

Add new top-level folders only when an implemented subsystem needs them.

## Environment

- Python 3.11 or newer.
- Create and activate a virtual environment.
- Install project and development dependencies.
- Copy `.env.example` to `.env` and add only required local secrets.
- Run `python -m decode --doctor` or the relevant health command before tool-backed work.

## Coding standards

- Add type hints to every function signature.
- Follow neighboring import, logging, error, and formatting patterns.
- Use relative imports inside `decode/`.
- Prefer Pydantic models at trust and serialization boundaries.
- Use `log_action()` from `decode.utils` where the established path requires it.
- Keep new behavior behind the governed capabilities; never add a raw-shell path.
- Do not add explanatory code comments unless needed to clarify a non-obvious invariant.

## No hardcoded tools

The agent runs installed tools through the governed `shell_command` capability
after discovering them with `list_tools`. Do **not** add per-tool Python wrappers,
a tool catalog, or tool-name branches. A missing tool is reported, never
auto-installed. New host primitives (if genuinely needed) are added to
`decode/hostcontrol/operations.py` and wired through `HostAgent`.

## Adding a markdown playbook

Reusable procedures are authored as markdown, not Python:

1. Create a `.md` file in `decode/skills/playbooks/` (or a dir on `DECODE_PLAYBOOKS_DIR`).
2. Add YAML frontmatter: `name`, `description`, `category`, `risk`, `tags`, optional `inputs`/`target_required`.
3. Write the body as step-by-step instructions the agent executes via `shell_command`.
4. Add coverage in `tests/test_markdown_skills.py` if the playbook needs guaranteed discovery.

Registration is automatic through `SkillRegistry` (see `decode/skills/markdown_skill.py`).

## Extensions

There is no in-tree plugin system — `decode/tools.py` and `decode/plugins/` were
removed. Extend Decode through:

- **Markdown playbooks** (above) for repeatable procedures.
- **Native capabilities** in `decode/hostcontrol/operations.py` (wired through
  `HostAgent`) for genuinely new OS primitives.

Optional connectors to *external* systems are a planned, isolated plugin surface,
not an in-tree one. See [PLUGIN_MANIFEST.md](PLUGIN_MANIFEST.md).

## Error handling

- Use stable error categories at boundaries.
- Preserve original exceptions for internal diagnostics without leaking secrets.
- Distinguish invalid input, policy denial, missing dependency, timeout, parser failure, and provider failure.
- Preserve raw output when normalization fails.
- Never convert denial into retry.

## Logging requirements

Every governed execution records:

- `LoggingService.log_execution()`.
- `AuditLayer.record_execution()`.
- `FeedbackStore.record_execution()`.

Do not log raw credentials, API keys, session tokens, or unrestricted sensitive artifacts.

## Testing

Run after every change:

```text
ruff check .
python -m pytest tests/
```

The `pytest tests/` launcher is also supported when the environment places the repository root on `sys.path`.

Add focused tests before broad integration tests. External tools and model APIs use fixtures or controlled opt-in integration tests.

## Documentation

- Update the maturity label when a planned capability becomes implemented.
- Link to source contracts rather than duplicating them.
- Document safety and failure behavior.
- Use non-routable, synthetic, or explicitly controlled example targets.
- Add an ADR for durable architectural decisions.

## Git strategy

- Keep changes focused.
- Preserve unrelated working-tree modifications.
- Use branches prefixed with `codex/` for Codex-created branches unless instructed otherwise.
- Do not commit generated runtime data, secrets, databases, logs, evidence, or model indexes.
- Never commit on behalf of a user unless explicitly asked.

## Code review

Reviewers check:

- Scope and permission invariants.
- Dependency validation.
- Command/path/input safety.
- Secret handling.
- Audit/log/feedback completeness.
- Parser robustness and raw evidence preservation.
- Backward compatibility and migrations.
- Tests for failures and policy boundaries.
- Documentation maturity claims.

## Versioning

Use semantic versioning for releases and explicit schema versions for events, plugins, prompts, APIs, registry entries, memory, and database migrations.

## Release process

1. Freeze scope and update changelog.
2. Run lint, unit, integration, security, and migration tests.
3. Verify documentation and examples.
4. Generate dependency inventory/SBOM.
5. Build artifacts in a clean environment.
6. Scan and sign release artifacts.
7. Publish checksums and upgrade notes.
8. Monitor regressions and retain rollback artifacts.
