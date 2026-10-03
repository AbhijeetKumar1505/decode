# Technology Stack

**Status:** Staged v2 target; adopt only in the owning phase

## Runtime

| Concern | Choice |
|---|---|
| Core | Python 3.12+ target, typing, Pydantic v2 |
| Async | `asyncio`, bounded task groups |
| FSM/DAG | typed FSM, custom scheduler; evaluate transitions/NetworkX |
| API | FastAPI/Uvicorn after contracts stabilize |
| State | SQLite, SQLAlchemy 2, Alembic target |
| Events/logs | typed append-only events; structlog target |
| Tests | pytest, pytest-asyncio, Hypothesis |
| Quality/package | Ruff, mypy, pre-commit, uv |

## Interfaces

Current Python Typer/Rich/prompt_toolkit. Target TypeScript/Node,
Commander/Ink/Zod API client. Later Tauri/React desktop. No second engine.

## Models, storage, execution

Provider-neutral gateway; OpenRouter/direct/local adapters; logical roles and
UTOS; no LangChain/LangGraph foundation. SQLite is canonical; JSON/Markdown/SARIF
exports; Tree-sitter before optional embeddings. The Engineering Knowledge Layer
starts with the existing SQLite graph tables, optional FTS5 indexing, and an
opt-in read-only Markdown vault adapter. A dedicated graph database is Research,
not a Phase 2 dependency. [Kuzu's upstream repository](https://github.com/kuzudb/kuzu)
was archived in 2025; evaluate its active successor
[LadybugDB](https://github.com/LadybugDB/ladybug) only if measured graph
traversal needs outgrow the SQLite baseline.

Targets are native Linux, explicit WSL distributions including Kali, Docker/OCI,
and explicit SSH/MCP. AWS is Deferred.

## Workflows and tools

Bridge definitions use Markdown frontmatter; Target definitions use validated
YAML. De-code avoids a hardcoded Kali catalog and per-tool Python wrappers:
installed CLIs run through the governed `shell_command` capability, while
markdown playbooks provide methodology. Providers own discovery/transport;
host contracts and the coordinator bind risk, scope, outcomes, and evidence.
Browser/search/authenticated sessions require explicit providers.

Pin dependencies and lockfiles, isolate optional integrations, verify integrity
and licenses, run supply-chain checks, and require owner/phase/rollback/security
rationale for additions.
