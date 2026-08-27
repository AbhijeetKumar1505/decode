import tempfile
import unittest
from pathlib import Path

import mongomock

from decode.memory import MemoryManager
from decode.persistence.migrate import migrate_sqlite_to_mongo
from decode.persistence.mongo_store import MongoSessionStore, build_mongo_uri
from decode.persistence.store import SessionStore


def _mongo_store(tmp: str) -> MongoSessionStore:
    return MongoSessionStore(
        client=mongomock.MongoClient(),
        db_name="decode_test",
        evidence_path=Path(tmp) / "evidence",
    )


class TestMongoUri(unittest.TestCase):
    def test_password_placeholder_is_substituted_and_encoded(self):
        uri = build_mongo_uri(
            "mongodb+srv://u:<db_password>@c.example.net/?appName=A",
            password="p@ss/w:rd",
        )
        self.assertNotIn("<db_password>", uri)
        self.assertIn("p%40ss%2Fw%3Ard", uri)

    def test_missing_uri_raises(self):
        with self.assertRaises(ValueError):
            build_mongo_uri("", password="x")


class TestMongoStoreContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = _mongo_store(self.tmp.name)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_session_finding_evidence_roundtrip(self):
        sid = self.store.create_session(goal="controlled test")
        self.assertEqual(self.store.get_session(sid)["goal"], "controlled test")

        fid = self.store.add_finding(sid, title="Open port", severity="low")
        eid = self.store.add_evidence(
            sid, type="command_output", label="scan", data={"ports": [80]}, finding_id=fid
        )
        finding = self.store.get_findings(sid)[0]
        self.assertIn(eid, finding["evidence_ids"])
        self.assertEqual(self.store.get_evidence(finding_id=fid)[0]["id"], eid)

        context = self.store.get_session_context(sid)
        self.assertEqual(len(context["findings"]), 1)
        # returned documents never leak the Mongo _id field
        self.assertNotIn("_id", self.store.get_session(sid))

    def test_project_memory_lifecycle(self):
        pid = self.store.create_project(name="isolated")
        memory = MemoryManager(self.store, project_id=pid)
        memory.project.remember("host", "192.0.2.10", "lab host")
        memory.knowledge.learn(
            "Nginx", "Observed service",
            provenance={"source": "evidence:123", "verification": "observed"},
        )

        results = memory.retrieve("Nginx")
        self.assertEqual(results[0]["source"], "project_graph")
        self.assertEqual(results[0]["provenance"]["source"], "evidence:123")

        exported = memory.export()
        self.assertEqual(exported["project"]["id"], pid)
        self.assertIsNotNone(memory.compress())
        # deletion removes the project and its isolated data
        self.assertGreaterEqual(memory.delete(), 1)
        self.assertIsNone(self.store.get_project(pid))


class TestSqliteToMongoMigration(unittest.TestCase):
    def test_migration_copies_rows(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)

        sqlite = SessionStore(db_path=Path(tmp.name) / "decode.db")
        sid = sqlite.create_session(goal="legacy")
        fid = sqlite.add_finding(sid, title="legacy finding")
        sqlite.add_evidence(sid, type="command_output", label="e", data={"a": 1}, finding_id=fid)
        sqlite.close()

        mongo = _mongo_store(tmp.name)
        self.addCleanup(mongo.close)
        summary = dict(migrate_sqlite_to_mongo(Path(tmp.name) / "decode.db", mongo))

        self.assertEqual(summary["sessions"], 1)
        self.assertEqual(summary["findings"], 1)
        self.assertEqual(mongo.get_session(sid)["goal"], "legacy")
        self.assertEqual(mongo.get_findings(sid)[0]["title"], "legacy finding")


if __name__ == "__main__":
    unittest.main()
