# Technology Stack

## Decision policy

Dependencies are adopted only when they serve a defined contract, have an acceptable security and maintenance profile, and preserve the local-first deployment. “Planned” technologies are candidates, not current installation requirements.

## Current stack

| Technology | Purpose | Advantages | Limitations | Alternatives considered |
|---|---|---|---|---|
| Python | Agent loop, host control, governance, integrations | Security ecosystem, rapid iteration, typing and async support | Runtime packaging and CPU-bound performance | Rust or Go for selected workers |
| Pydantic | Typed boundaries and validation | Explicit schemas, serialization, useful errors | Validation overhead and version coupling | Dataclasses, attrs |
| Typer | CLI command surface | Type-driven commands and help | CLI only; no service API | Click, argparse |
| Rich | Terminal rendering | Tables, panels, Markdown, portable output | Terminal rendering is not a stable machine API | Plain text, Textual |
| prompt_toolkit | Inline REPL and history | Mature interactive input | Single-process terminal focus | Textual, web UI |
| asyncio | Agent and executor concurrency | Standard library, good subprocess integration | Blocking SDKs require care | Trio, anyio |
| SQLite | Local operational persistence | Zero service dependency, transactional, portable | Limited distributed concurrency | PostgreSQL |
| FAISS | Optional vector retrieval foundation | Local and fast similarity search | Index operations and packaging complexity | Qdrant, pgvector |
| NetworkX | Knowledge/attack graph operations where used | Flexible graph algorithms | In-memory scaling | Neo4j, PostgreSQL graph extensions |
| Jinja2 | Report and prompt templating | Mature and auditable templates | Template injection requires controlled inputs | Native formatting |
| OpenAI SDK | Default orchestrator adapter (used for OpenRouter's OpenAI-compatible API and for OpenAI directly) | One client for the OpenRouter gateway and OpenAI; broad model capabilities | External service, cost, provider dependency | Anthropic, local models |
| OpenRouter | Default model gateway | One key unlocks many hosted models; OpenAI-compatible; retries transient 429/5xx | Meta-provider; free tiers share rate-limited upstream pools | OpenAI/Anthropic direct, local models |
| Anthropic SDK | Optional model adapter | Strong analysis models | External service, cost, provider dependency | OpenAI, OpenRouter, local models |
| Docker SDK | Isolated tool execution | Reproducible images and boundaries | Daemon privilege and host exposure risks | Podman, native sandbox |
| Requests | HTTP security integrations | Simple, widely supported | Synchronous by default | httpx, aiohttp |
| pytest | Automated testing | Mature ecosystem and fixtures | LLM and external-tool tests need isolation | unittest |
| Ruff | Lint and static style checks | Fast and deterministic | Not a type checker | Flake8, pylint |

## Execution platforms

| Platform | Purpose | Status | Constraints |
|---|---|---|---|
| Native Linux | Direct access to security tools | Implemented through local executor | Host impact must be policy-controlled |
| Windows | Local control plane and native tooling | Implemented | Tool compatibility varies |
| WSL | Linux/Kali tooling from Windows | Implemented | Distribution and path translation |
| Docker | Isolated and reproducible execution | Implemented | Container escape and socket exposure risks |
| SSH | Explicit remote execution | Implemented | Host keys, credentials, and remote policy |
| MCP | External tool/service protocol | Implemented foundation | Server trust and schema validation |

## Security tools (Kali and others)

Security tools are an execution environment, not Python dependencies. The agent
discovers whatever is installed at runtime via the `list_tools` capability (a
`$PATH` scan) and runs any of them — plus your own scripts — through governed
`shell_command`. There is no hardcoded tool catalog, per-tool wrapper, or
kernel-specific import; a missing tool is reported, never auto-installed.

## Dependency requirements

- Pin production dependencies and record provenance.
- Separate required, optional, development, and executor-specific dependencies.
- Report — never auto-install — a missing external tool the agent tries to run.
- Generate and review software bills of materials for releases.
- Scan Python, container, and plugin dependencies.
- Avoid loading optional SDKs until their provider is selected.

## Version baseline

Project code, packaging metadata, and continuous integration target Python 3.11 or newer.
