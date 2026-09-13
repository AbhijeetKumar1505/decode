import tempfile
import unittest
from pathlib import Path

from decode.memory import SENSITIVE_TYPES, MemoryManager, ProjectMemory, SessionMemory
from decode.persistence.store import SessionStore


class TestStoreProjectsArtifacts(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = SessionStore(db_path=self.tmp / "decode.db")

    def tearDown(self):
        self.store.close()

    def test_project_roundtrip(self):
        pid = self.store.create_project(name="Acme engagement", scope="10.0.0.0/24")
        proj = self.store.get_project(pid)
        self.assertEqual(proj["name"], "Acme engagement")
        self.assertIn(proj["id"], [p["id"] for p in self.store.list_projects()])

    def test_artifact_filtering(self):
        pid = self.store.create_project(name="p")
        self.store.add_artifact("host", "10.0.0.5", project_id=pid)
        self.store.add_artifact(
            "credential", "admin", "hunter2", project_id=pid, sensitive=True
        )
        hosts = self.store.get_artifacts(project_id=pid, type="host")
        self.assertEqual(len(hosts), 1)
        self.assertEqual(hosts[0]["key"], "10.0.0.5")
        creds = self.store.get_artifacts(project_id=pid, type="credential")
        self.assertEqual(creds[0]["sensitive"], 1)


class TestSessionMemory(unittest.TestCase):
    def test_scratch(self):
        m = SessionMemory("s1")
        m.set("phase", "recon")
        self.assertEqual(m.get("phase"), "recon")
        self.assertEqual(m.get("missing", "d"), "d")
        self.assertEqual(m.all(), {"phase": "recon"})


class TestProjectMemory(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = SessionStore(db_path=self.tmp / "decode.db")

    def tearDown(self):
        self.store.close()

    def test_sensitive_types_auto_flagged(self):
        pid = self.store.create_project(name="p")
        pm = ProjectMemory(self.store, project_id=pid)
        pm.remember("token", "jwt-abc", "eyJ...")
        tokens = pm.recall(type="token")
        self.assertEqual(tokens[0]["sensitive"], 1)
        self.assertIn("token", SENSITIVE_TYPES)

    def test_hosts_persist_across_sessions(self):
        pid = self.store.create_project(name="p")
        sess_a = self.store.create_session(goal="a")
        sess_b = self.store.create_session(goal="b")
        pm = ProjectMemory(self.store, project_id=pid)
        pm.remember("host", "10.0.0.5", session_id=sess_a)
        pm.remember("host", "10.0.0.6", session_id=sess_b)
        self.assertEqual(len(pm.hosts()), 2)


class TestMemoryManager(unittest.TestCase):
    def test_capture_host(self):
        tmp = Path(tempfile.mkdtemp())
        store = SessionStore(db_path=tmp / "decode.db")
        pid = store.create_project(name="p")
        sid = store.create_session(goal="s")
        mm = MemoryManager(store, session_id=sid, project_id=pid)
        mm.capture_host("10.0.0.5")
        self.assertEqual(len(mm.project.hosts()), 1)
        self.assertIsNone(mm.capture_host(""))  # empty host is a no-op
        store.close()


if __name__ == "__main__":
    unittest.main()


import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import mongomock
import pytest

from decode.memory import GlobalMemory, SelfLearningMemory, UserMemory
from decode.persistence.mongo_store import MongoSessionStore


@pytest.fixture(params=["sqlite", "mongo"])
def lifecycle_store(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[SessionStore | MongoSessionStore]:
    store = (
        SessionStore(tmp_path / "memory.db")
        if request.param == "sqlite"
        else MongoSessionStore(
            client=mongomock.MongoClient(), evidence_path=tmp_path / "evidence"
        )
    )
    yield store
    store.close()


def test_scope_isolation_and_explicit_global(
    lifecycle_store: SessionStore | MongoSessionStore,
) -> None:
    store = lifecycle_store
    project = store.create_project("p")
    other = store.create_project("other")
    sid = store.create_session()
    store.add_artifact("note", "shared", "session", session_id=sid)
    ProjectMemory(store, project).remember("note", "shared", "project")
    ProjectMemory(store, other).remember("note", "shared", "other project")
    UserMemory(store, "alice").remember("note", "shared", "alice")
    UserMemory(store, "bob").remember("note", "shared", "bob")
    GlobalMemory(store).remember("note", "shared", "global")
    memory = MemoryManager(store, project_id=project, user_id="alice")
    assert {item["record"]["value"] for item in memory.retrieve("shared")} == {
        "project",
        "alice",
    }
    memory = MemoryManager(store, user_id="alice", include_global=True)
    assert {item["record"]["value"] for item in memory.retrieve("shared")} == {
        "alice",
        "global",
    }
    assert MemoryManager(store).retrieve("shared") == []
    assert ProjectMemory(store).recall() == []
    with pytest.raises(ValueError):
        ProjectMemory(store).remember("note", "x")
    with pytest.raises(ValueError):
        UserMemory(store, " ")
    with pytest.raises(ValueError):
        store.add_artifact("note", "x", scope="global", project_id=project)


def test_versions_expiry_confidence_and_scoped_deletion(
    lifecycle_store: SessionStore | MongoSessionStore,
) -> None:
    memory = UserMemory(lifecycle_store, "alice")
    aid = memory.remember("note", "service", "old", confidence=0.2)
    assert memory.edit(aid, expected_version=1, value="new", confidence=0.9) == 2
    assert [item["value"] for item in memory.history(aid)] == ["old", "new"]
    with pytest.raises(ValueError, match="version conflict"):
        memory.edit(aid, expected_version=1, value="lost update")
    other = UserMemory(lifecycle_store, "bob")
    with pytest.raises(ValueError, match="not found"):
        other.edit(aid, expected_version=2, value="cross scope")
    assert other.history(aid) == []
    assert not other.forget(aid)
    memory.edit(
        aid, expected_version=2, expires_at=datetime.now(UTC) - timedelta(seconds=1)
    )
    assert memory.recall() == []
    assert len(memory.history(aid)) == 3
    memory.edit(aid, expected_version=3, expires_at=None)
    assert len(memory.recall()) == 1
    assert memory.forget(aid)
    assert memory.history(aid) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"confidence": -0.1},
        {"confidence": 1.1},
        {"confidence": float("nan")},
        {"confidence": float("inf")},
        {"expires_at": "2026-01-01"},
        {"expires_at": "invalid"},
    ],
)
def test_invalid_lifecycle_metadata(
    lifecycle_store: SessionStore | MongoSessionStore, changes: dict
) -> None:
    memory = GlobalMemory(lifecycle_store)
    with pytest.raises(ValueError):
        memory.remember("note", "key", **changes)
    aid = memory.remember("note", "key")
    with pytest.raises(ValueError):
        memory.edit(aid, expected_version=1, **changes)
    assert memory.recall()[0]["version"] == 1


def test_sensitive_history_never_leaks_into_exports_or_retrieval(
    lifecycle_store,
) -> None:
    pid = lifecycle_store.create_project("p")
    memory = MemoryManager(lifecycle_store, project_id=pid)
    aid = memory.project.remember(
        "token", "synthetic-key-one", "synthetic-secret-one", sensitive=False
    )
    memory.project.edit(
        aid, expected_version=1, key="synthetic-key-two", value="synthetic-secret-two"
    )
    serialized = json.dumps(memory.export()) + json.dumps(memory.project.history(aid))
    assert "synthetic-secret" not in serialized
    assert "synthetic-key" not in serialized
    assert memory.retrieve("synthetic") == []
    with pytest.raises(ValueError):
        memory.project.edit(aid, expected_version=2, sensitive=False)
    assert "synthetic-secret-one" in json.dumps(memory.export(include_sensitive=True))
    with pytest.raises(ValueError):
        memory.project.edit(aid, expected_version=2, project_id="other")


def test_legacy_sqlite_artifacts_are_migrated_on_reopen(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE artifacts (id TEXT PRIMARY KEY, project_id TEXT,
                session_id TEXT, type TEXT, key TEXT, value TEXT, sensitive INTEGER,
                created_at TEXT);
            INSERT INTO artifacts VALUES ('a', 'p', NULL, 'note', 'key', 'old', 0,
                '2026-01-01T00:00:00+00:00');
        """)
    for _ in range(2):
        store = SessionStore(path)
        try:
            record = store.get_artifacts(project_id="p", scope="project")[0]
            assert record["version"] == 1
            assert record["updated_at"] == record["created_at"]
        finally:
            store.close()


def test_legacy_mongo_artifact_can_be_versioned(tmp_path: Path) -> None:
    store = MongoSessionStore(
        client=mongomock.MongoClient(), evidence_path=tmp_path / "e"
    )
    store._db.artifacts.insert_one(
        {
            "id": "a",
            "project_id": "p",
            "session_id": None,
            "type": "note",
            "key": "k",
            "value": "old",
            "sensitive": 0,
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    )
    assert ProjectMemory(store, "p").edit("a", expected_version=1, value="new") == 2
    assert len(ProjectMemory(store, "p").history("a")) == 2
    store.close()


class OfflineEmbeddings:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0] if "service" in text else [0.0, 1.0]


def test_semantic_snapshot_roundtrip_and_scoped_hybrid(
    tmp_path: Path, lifecycle_store
) -> None:
    pid = lifecycle_store.create_project("p")
    backend = SelfLearningMemory(
        tmp_path / "index", project_id=pid, embeddings=OfflineEmbeddings()
    )
    backend.add_experience("service", "read", "observed", True)
    reopened = SelfLearningMemory(
        tmp_path / "index", project_id=pid, embeddings=OfflineEmbeddings()
    )
    assert reopened.retrieve_relevant("service", k=5) == backend.knowledge
    assert len(reopened.knowledge) == 1
    memory = MemoryManager(lifecycle_store, project_id=pid, semantic_memory=reopened)
    result = memory.retrieve("service")[0]
    assert result["source"] == "semantic"
    assert result["provenance"]["verification"] == "unverified"
    with pytest.raises(ValueError, match="scope"):
        MemoryManager(lifecycle_store, project_id="another", semantic_memory=reopened)
    with pytest.raises(ValueError, match="another project"):
        SelfLearningMemory(
            tmp_path / "index", project_id="another", embeddings=OfflineEmbeddings()
        )
    memory.delete()
    assert reopened.retrieve_relevant("service") == []
    assert (
        SelfLearningMemory(
            tmp_path / "index", project_id=pid, embeddings=OfflineEmbeddings()
        ).knowledge
        == []
    )


def test_semantic_opt_in_and_safe_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    disabled = SelfLearningMemory(tmp_path / "disabled")
    assert disabled.retrieve_relevant("anything") == []
    assert not (tmp_path / "disabled").exists()
    backend = SelfLearningMemory(
        tmp_path / "index",
        project_id="p",
        embeddings=OfflineEmbeddings(),
        initial_knowledge=["service"],
    )
    with patch.object(
        backend.embeddings, "embed_query", side_effect=RuntimeError("synthetic-secret")
    ):
        assert backend.retrieve_relevant("service") == []
    assert "synthetic-secret" not in caplog.text
    with pytest.raises(ValueError):
        backend.retrieve_relevant("service", k=0)
    with patch.object(backend.embeddings, "embed_query", return_value=[1.0]):
        assert backend.retrieve_relevant("service") == []
    for kwargs in ({"sensitive": True}, {}):
        with patch.object(backend.embeddings, "embed_query", Mock()) as embed:
            with pytest.raises(ValueError):
                backend.add_experience(
                    "password=synthetic", "read", "ok", True, **kwargs
                )
            embed.assert_not_called()
    with patch("os.replace", side_effect=OSError("disk unavailable")):
        with pytest.raises(OSError):
            backend.add_experience("service", "read", "new", True)
    assert backend.knowledge == ["service"]
    assert SelfLearningMemory(
        tmp_path / "index", project_id="p", embeddings=OfflineEmbeddings()
    ).knowledge == ["service"]
