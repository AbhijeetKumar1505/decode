# Memory Engine Implementation Note

The canonical memory contract is [Memory Architecture](MEMORY_ARCHITECTURE.md), and the exact current tables are listed in [Database Schema](DATABASE_SCHEMA.md).

## Current components

| Component | Source | State |
|---|---|---|
| Session and project store | `decode/persistence/store.py` | SQLite-backed |
| Target tracker | `decode/persistence/target_tracker.py` | Targets, ports, findings, and evidence |
| Evidence service | `decode/persistence/evidence.py` | Hash and chain-of-custody foundations |
| Scoped memory | `src/decode/memory/layers.py` | Project/user/global artifacts, revisions, expiry and retrieval |
| Session memory | `decode/memory/layers.py` | In-process bounded context |
| Knowledge graph | `decode/knowledge/graph.py` | Entity and relationship storage |
| Semantic backend | `src/decode/memory/self_learning.py` | Opt-in project-bound FAISS retrieval; autonomous learning remains research |

The SQLite schema currently contains `sessions`, `projects`, `targets`, `ports`, `findings`, `evidence`, and `artifacts`. Large or sensitive evidence should be stored through protected artifact/evidence handling and referenced from operational records.

## Trust rules

- Tool and model outputs are observations until verified.
- Raw evidence is immutable after registration.
- Every durable item needs project/session scope and provenance.
- Sensitive content must use redacted rendering and protected storage.
- Context building must be bounded and must not copy secrets into model prompts.
- Artifact expiry, versioned edits, export, and deletion are explicit APIs; background retention and automatic promotion remain unimplemented.

## Usage

Use `create_store()` and `TargetContextTracker` for current session-oriented operations. Use `ProjectMemory` for project artifacts. Do not write directly to SQLite from a skill when a repository service exists.

```python
from decode.persistence import create_store, TargetContextTracker

store = create_store()
tracker = TargetContextTracker(store)
session_id = tracker.start_session(
    goal="Review an authorized lab service",
    target_focus="192.0.2.10",
)
```

Use synthetic targets in examples and tests. Database location defaults to `data/decode.db`; runtime database, WAL, evidence, logs, audit, feedback, and model indexes may contain sensitive user data and must not be committed.
