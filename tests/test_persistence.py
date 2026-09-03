import json
import stat
import tempfile
import unittest
from pathlib import Path

from decode.persistence.evidence import (
    Evidence,
    EvidenceCollector,
    EvidenceReference,
    ProtectedEvidenceStore,
)
from decode.persistence.store import SessionStore
from decode.persistence.target_tracker import TargetContextTracker, TargetFinding


class TestSessionStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = SessionStore(Path(self.tmp) / "test.db")

    def tearDown(self):
        self.store.close()
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_create_session(self):
        sid = self.store.create_session(goal="Test assessment", target_focus="10.0.0.1")
        self.assertIsNotNone(sid)
        session = self.store.get_session(sid)
        self.assertEqual(session["goal"], "Test assessment")

    def test_list_sessions(self):
        self.store.create_session(goal="Goal 1")
        self.store.create_session(goal="Goal 2")
        sessions = self.store.list_sessions()
        self.assertEqual(len(sessions), 2)

    def test_close_session(self):
        sid = self.store.create_session()
        self.store.close_session(sid)
        session = self.store.get_session(sid)
        self.assertEqual(session["status"], "closed")

    def test_upsert_target(self):
        sid = self.store.create_session()
        tid = self.store.upsert_target(sid, hostname="example.com", ip="10.0.0.1")
        self.assertIsNotNone(tid)
        target = self.store.get_target(tid)
        self.assertEqual(target["hostname"], "example.com")

    def test_upsert_port(self):
        sid = self.store.create_session()
        tid = self.store.upsert_target(sid, hostname="test.local", ip="10.0.0.1")
        pid = self.store.upsert_port(
            tid, port=80, service="http", product="nginx", version="1.24"
        )
        self.assertIsNotNone(pid)
        ports = self.store.get_ports(tid)
        self.assertEqual(len(ports), 1)
        self.assertEqual(ports[0]["port"], 80)
        self.assertEqual(ports[0]["service"], "http")

    def test_upsert_port_updates_existing(self):
        sid = self.store.create_session()
        tid = self.store.upsert_target(sid, ip="10.0.0.1")
        pid1 = self.store.upsert_port(tid, port=80, service="http")
        pid2 = self.store.upsert_port(tid, port=80, service="http", product="Apache")
        self.assertEqual(pid1, pid2)  # Same port → same ID
        ports = self.store.get_ports(tid)
        self.assertEqual(ports[0]["product"], "Apache")

    def test_add_finding(self):
        sid = self.store.create_session()
        fid = self.store.add_finding(
            sid, title="Open port 80", severity="medium", category="recon"
        )
        self.assertIsNotNone(fid)
        findings = self.store.get_findings(sid)
        self.assertEqual(len(findings), 1)

    def test_add_evidence(self):
        sid = self.store.create_session()
        eid = self.store.add_evidence(
            sid,
            type="command_output",
            label="Nmap scan",
            data={"ports": [80]},
            source="nmap",
        )
        self.assertIsNotNone(eid)
        evidence = self.store.get_evidence(session_id=sid)
        self.assertEqual(len(evidence), 1)
        reference = EvidenceReference(**json.loads(evidence[0]["data"]))
        evidence_store = ProtectedEvidenceStore(Path(self.tmp) / "evidence")
        self.assertTrue(evidence_store.verify(reference))
        self.assertNotIn("ports", evidence[0]["data"])

    def test_session_context(self):
        sid = self.store.create_session(goal="Assess target")
        tid = self.store.upsert_target(sid, hostname="test.local", ip="10.0.0.1")
        self.store.upsert_port(tid, port=443, service="https")
        self.store.add_finding(sid, title="HTTPS open", severity="medium")
        ctx = self.store.get_session_context(sid)
        self.assertEqual(len(ctx["targets"]), 1)
        self.assertEqual(len(ctx["targets"][0]["ports"]), 1)
        self.assertEqual(len(ctx["findings"]), 1)

    def test_add_evidence_with_finding(self):
        sid = self.store.create_session()
        fid = self.store.add_finding(sid, title="Test", severity="low")
        eid = self.store.add_evidence(
            sid, type="test", label="Evidence", data={"key": "val"}, finding_id=fid
        )
        evidence = self.store.get_evidence(finding_id=fid)
        self.assertEqual(len(evidence), 1)
        # Check finding references this evidence
        finding = self.store.get_findings(sid)[0]
        import json

        self.assertIn(eid, json.loads(finding["evidence_ids"]))


class TestTargetContextTracker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = SessionStore(Path(self.tmp) / "tracker.db")
        self.tracker = TargetContextTracker(self.store)

    def tearDown(self):
        self.store.close()
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_flow(self):
        sid = self.tracker.start_session(
            goal="Audit web server", target_focus="example.com"
        )
        self.assertIsNotNone(sid)
        self.tracker.track_target(hostname="example.com", ip="93.184.216.34")
        self.tracker.record_port(80, service="http", product="nginx")
        self.tracker.record_port(443, service="https", product="nginx")
        finding = TargetFinding(
            title="Nginx detected",
            description="Nginx on 80/443",
            severity="medium",
            category="fingerprinting",
        )
        fid = self.tracker.record_finding(finding)
        self.assertIsNotNone(fid)
        eid = self.tracker.record_evidence(
            type="scan_result",
            label="Nmap of example.com",
            data={"ports": [80, 443]},
            source="nmap",
        )
        self.assertIsNotNone(eid)
        ctx = self.tracker.build_context_prompt()
        self.assertIn("Audit web server", ctx)
        self.assertIn("example.com", ctx)
        self.assertIn("443", ctx)
        ports = self.tracker.get_open_ports_summary()
        self.assertEqual(len(ports), 2)

    def test_no_session_raises(self):
        with self.assertRaises(RuntimeError):
            self.tracker.track_target(hostname="test")


class TestEvidenceCollector(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.collector = EvidenceCollector(Path(self.tmp.name) / "evidence")

    def tearDown(self):
        self.tmp.cleanup()

    def test_collect(self):
        ev = self.collector.collect(
            "finding", "Test finding", {"detail": "info"}, source="test"
        )
        self.assertIsInstance(ev, Evidence)
        self.assertEqual(ev.type, "finding")

    def test_collect_command_output(self):
        ev = self.collector.collect_command_output(
            "nmap -sV target", "stdout here", "stderr here", 0, "nmap"
        )
        self.assertEqual(ev.type, "command_output")
        self.assertNotIn("command", ev.data)
        self.assertTrue(Path(ev.reference.path).is_file())
        payload = json.loads(Path(ev.reference.path).read_text(encoding="utf-8"))
        self.assertEqual(payload["command"], "nmap -sV target")

    def test_collect_scan_result(self):
        ev = self.collector.collect_scan_result(
            "nmap", "10.0.0.1", "raw data", {"ports": [80]}
        )
        self.assertEqual(ev.type, "scan_result")

    def test_get_by_type(self):
        self.collector.collect("type_a", "A", {})
        self.collector.collect("type_b", "B", {})
        self.collector.collect("type_a", "A2", {})
        self.assertEqual(len(self.collector.get_by_type("type_a")), 2)
        self.assertEqual(len(self.collector.get_by_type("type_b")), 1)

    def test_get_by_source(self):
        self.collector.collect("t", "A", {}, source="nmap")
        self.collector.collect("t", "B", {}, source="whatweb")
        self.assertEqual(len(self.collector.get_by_source("nmap")), 1)

    def test_clear(self):
        self.collector.collect("t", "A", {})
        self.collector.clear()
        self.assertEqual(len(self.collector.get_all()), 0)

    def test_protected_evidence_is_immutable_and_hash_verified(self):
        store = ProtectedEvidenceStore(Path(self.tmp.name) / "protected")
        reference = store.capture({"raw": "first"}, evidence_id="fixed-id")

        self.assertTrue(store.verify(reference))
        self.assertEqual(stat.S_IMODE(store.base_path.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(Path(reference.path).stat().st_mode), 0o600)
        with self.assertRaisesRegex(RuntimeError, "immutable evidence"):
            store.capture({"raw": "changed"}, evidence_id="fixed-id")

    def test_protected_evidence_rejects_foreign_reference(self):
        root = Path(self.tmp.name)
        owner = ProtectedEvidenceStore(root / "owner")
        other = ProtectedEvidenceStore(root / "other")
        reference = owner.capture("raw output")

        self.assertFalse(other.verify(reference))


if __name__ == "__main__":
    unittest.main()
