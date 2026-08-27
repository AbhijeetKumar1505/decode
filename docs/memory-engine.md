# Memory Engine Implementation Note

The canonical memory contract is [Memory Architecture](MEMORY_ARCHITECTURE.md), and the exact current tables are listed in [Database Schema](DATABASE_SCHEMA.md).

## Current components

| Component | Source | State |
|---|---|---|
| Session and project store | `decode/persistence/store.py` | SQLite-backed |
| Target tracker | `decode/persistence/target_tracker.py` | Targets, ports, findings, and evidence |
| Evidence service | `decode/persistence/evidence.py` | Hash and chain-of-custody foundations |
| Project memory | `decode/memory/layers.py` | Project artifact metadata and retrieval |
| Session memory | `decode/memory/layers.py` | In-process bounded context |
| Knowledge graph | `decode/knowledge/graph.py` | Entity and relationship storage |
| Self-learning | `decode/memory/self_learning.py` | Prototype, not autonomous production learning |

The SQLite schema currently contains `sessions`, `projects`, `targets`, `ports`, `findings`, `evidence`, and `artifacts`. Large or sensitive evidence should be stored through protected artifact/evidence handling and referenced from operational records.

## Trust rules

- Tool and model outputs are observations until verified.
- Raw evidence is immutable after registration.
- Every durable item needs project/session scope and provenance.
- Sensitive content must use redacted rendering and protected storage.
- Context building must be bounded and must not copy secrets into model prompts.
- Retention, export, compression, and deletion are explicit policy work; they are not automatic defaults today.

## Usage

Use `SessionStore` and `TargetContextTracker` for current session-oriented operations. Use `ProjectMemory` for project artifacts. Do not write directly to SQLite from a skill when a repository service exists.

```python
from decode.persistence import SessionStore, TargetContextTracker

store = SessionStore()
tracker = TargetContextTracker(store)
session_id = tracker.start_session(
    goal="Review an authorized lab service",
    target_focus="192.0.2.10",
)
```

Use synthetic targets in examples and tests. Database location defaults to `data/decode.db`; runtime database, WAL, evidence, logs, audit, feedback, and model indexes may contain sensitive user data and must not be committed.
