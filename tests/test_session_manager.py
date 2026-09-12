"""Tests for the core SessionManager and the dc_ session-id format."""

import os
import re
import tempfile
import unittest
from pathlib import Path

from decode.app.config import Config
from decode.persistence.manager import SessionManager
from decode.persistence.store import SessionStore

_DC_ID = re.compile(r"^dc_\d{8}_[0-9a-f]{8}$")


class SessionManagerTest(unittest.TestCase):
    def setUp(self):
        self._prev_home = os.environ.get("DECODE_HOME")
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DECODE_HOME"] = self._tmp.name
        Config.reload()
        Config.ensure_dirs()
        # Construct SQLite directly so the test is isolated regardless of a
        # configured MONGODB_URI (create_store() would otherwise use Mongo).
        self.mgr = SessionManager(
            SessionStore(db_path=Path(self._tmp.name) / "decode.db")
        )

    def tearDown(self):
        if self._prev_home is None:
            os.environ.pop("DECODE_HOME", None)
        else:
            os.environ["DECODE_HOME"] = self._prev_home
        Config.reload()
        self._tmp.cleanup()

    def test_create_uses_dc_id_format(self):
        sid = self.mgr.create(goal="scan the box", target_focus="10.0.0.5")
        self.assertRegex(sid, _DC_ID)

    def test_list_and_latest(self):
        first = self.mgr.create(goal="first")
        second = self.mgr.create(goal="second")
        listed = self.mgr.list()
        self.assertEqual({s["id"] for s in listed}, {first, second})  # isolated
        self.assertEqual(self.mgr.latest()["id"], second)

    def test_resolve(self):
        sid = self.mgr.create(goal="g")
        self.assertEqual(self.mgr.resolve(resume=sid), sid)
        self.assertIsNone(self.mgr.resolve(resume="dc_20000101_deadbeef"))
        self.assertEqual(self.mgr.resolve(continue_last=True), sid)
        self.assertIsNone(self.mgr.resolve())

    def test_transcript_roundtrip(self):
        sid = self.mgr.create()
        convo = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "yo"},
        ]
        self.mgr.save_transcript(sid, convo)
        self.assertEqual(self.mgr.load_transcript(sid), convo)
        self.assertEqual(self.mgr.load_transcript("dc_20000101_deadbeef"), [])

    def test_usage_accumulates(self):
        sid = self.mgr.create(goal="probe")
        self.assertEqual(self.mgr.usage(sid)["cost_usd"], 0.0)
        self.mgr.record_usage(
            sid, prompt_tokens=100, completion_tokens=40, cost_usd=0.01, model="m"
        )
        self.mgr.record_usage(
            sid, prompt_tokens=50, completion_tokens=10, cost_usd=0.02, model="m"
        )
        usage = self.mgr.usage(sid)
        self.assertEqual(usage["prompt_tokens"], 150)
        self.assertEqual(usage["completion_tokens"], 50)
        self.assertAlmostEqual(usage["cost_usd"], 0.03)

    def test_status_and_lifecycle(self):
        sid = self.mgr.create(goal="probe", target_focus="host")
        status = self.mgr.status(sid)
        self.assertEqual(status["status"], "active")
        self.assertEqual(status["goal"], "probe")
        self.assertEqual(status["findings"], 0)
        self.mgr.close(sid)
        self.assertEqual(self.mgr.status(sid)["status"], "closed")
        self.mgr.reactivate(sid)
        self.assertEqual(self.mgr.status(sid)["status"], "active")
        self.assertIsNone(self.mgr.status("dc_20000101_deadbeef"))


class TaskStateStoreTest(unittest.TestCase):
    """Checkpointing a TaskState keyed by the live session id round-trips."""

    def setUp(self):
        self._prev_home = os.environ.get("DECODE_HOME")
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DECODE_HOME"] = self._tmp.name
        Config.reload()
        self.store = SessionStore(db_path=Path(self._tmp.name) / "decode.db")

    def tearDown(self):
        if self._prev_home is None:
            os.environ.pop("DECODE_HOME", None)
        else:
            os.environ["DECODE_HOME"] = self._prev_home
        Config.reload()
        self._tmp.cleanup()

    def test_checkpoint_round_trip(self):
        from decode.schema.store import TaskStateStore
        from decode.schema.task_state import ScopeView, TaskState

        sid = self.store.create_session(goal="probe", target_focus="10.0.0.5")
        store = TaskStateStore(self.store)
        self.assertIsNone(store.load(sid))  # nothing yet

        state = TaskState(
            session_id=sid,
            objective="probe",
            scope=ScopeView(targets=["10.0.0.5"]),
        )
        state.record_action("shell_command", {"command": "echo hi"})
        store.save(state)

        loaded = store.load(sid)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.session_id, sid)
        self.assertEqual(loaded.objective, "probe")
        self.assertEqual(len(loaded.actions), 1)


if __name__ == "__main__":
    unittest.main()
