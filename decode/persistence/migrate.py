"""One-shot migration of the local SQLite store into MongoDB.

Copies every row of each known table into the matching MongoDB collection,
preserving identifiers so the migration is idempotent (re-running replaces the
same documents). Raw evidence blobs are intentionally left on the local disk;
only their already-stored hashed references travel with the ``evidence`` rows.

Usage::

    python -m decode.persistence.migrate --sqlite data/decode.db
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from .. import config  # noqa: F401  (loads .env so MONGODB_URI is available)
from .mongo_store import MongoSessionStore

# collection -> function mapping a source row to its stable _id
_ID_STRATEGY: Dict[str, Callable[[Dict[str, Any]], str]] = {
    "sessions": lambda r: r["id"],
    "targets": lambda r: r["id"],
    "ports": lambda r: r["id"],
    "findings": lambda r: r["id"],
    "evidence": lambda r: r["id"],
    "projects": lambda r: r["id"],
    "artifacts": lambda r: r["id"],
    "missions": lambda r: r["session_id"],
    "mission_nodes": lambda r: f"{r['session_id']}:{r['node_id']}",
    "project_knowledge_nodes": lambda r: r["id"],
    "project_knowledge_edges": lambda r: r["id"],
    "memory_events": lambda r: r["id"],
}


def _existing_tables(conn: sqlite3.Connection) -> List[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return [row[0] for row in rows]


def migrate_sqlite_to_mongo(
    sqlite_path: Path, store: MongoSessionStore
) -> List[Tuple[str, int]]:
    """Copy all supported tables. Returns (collection, copied_count) pairs."""
    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row
    summary: List[Tuple[str, int]] = []
    try:
        tables = set(_existing_tables(conn))
        for table, id_of in _ID_STRATEGY.items():
            if table not in tables:
                continue
            collection = store._db[table]
            copied = 0
            for row in conn.execute(f"SELECT * FROM {table}"):  # nosec B608
                doc = dict(row)
                doc["_id"] = id_of(doc)
                collection.replace_one({"_id": doc["_id"]}, doc, upsert=True)
                copied += 1
            summary.append((table, copied))
    finally:
        conn.close()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate SQLite store to MongoDB")
    parser.add_argument("--sqlite", default="data/decode.db", help="SQLite database path")
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite)
    if not sqlite_path.exists():
        print(f"SQLite database not found: {sqlite_path}")
        return 2

    store = MongoSessionStore()
    try:
        store._db.command("ping")
    except Exception as exc:  # pragma: no cover - network/credential errors
        print(f"MongoDB connection failed: {type(exc).__name__}: {exc}")
        store.close()
        return 1

    try:
        summary = migrate_sqlite_to_mongo(sqlite_path, store)
    finally:
        store.close()

    total = sum(count for _, count in summary)
    for collection, count in summary:
        print(f"  {collection}: {count}")
    print(f"Migrated {total} documents from {sqlite_path} into MongoDB.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
