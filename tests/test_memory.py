import tempfile
import unittest
from pathlib import Path

from decode.persistence.store import SessionStore
from decode.memory import SessionMemory, ProjectMemory, MemoryManager, SENSITIVE_TYPES


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
        self.store.add_artifact("credential", "admin", "hunter2", project_id=pid, sensitive=True)
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
