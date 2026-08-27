import json
import os
import tempfile
import unittest
from pathlib import Path

from decode.persistence import SessionStore
from decode.persistence.evidence import EvidenceCollector
from decode.skills.registry import SkillRegistry
from decode.tui.app import AgentREPL


class _FakeAgent:
    provider_name = "openrouter"

    def __init__(self):
        self.conversation_history = []
        self.scope = None

    def set_scope(self, entries):
        self.scope = list(entries)


def _bare_repl(store) -> AgentREPL:
    r = AgentREPL.__new__(AgentREPL)
    r._store = store
    r._agent = _FakeAgent()
    r._registry = SkillRegistry()
    r._evidence = EvidenceCollector()
    r._scope_entries = []
    r._session_active = False
    r._tracker = None
    r._current_target = ""
    r._conversation_history = []
    r._resume_request = None
    r._continue_last = False
    return r


class TestResumeFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self._cwd)
        self.store = SessionStore(db_path=Path(self.tmp.name) / "data" / "decode.db")
        self.addCleanup(self.store.close)

    def _save_conversation(self, sid, history):
        path = Path("./data/sessions") / f"{sid}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(history), encoding="utf-8")

    def test_resume_restores_conversation_target_and_agent_context(self):
        sid = self.store.create_session(goal="lab audit", target_focus="192.0.2.5")
        history = [{"role": "user", "content": "profile the host"}]
        self._save_conversation(sid, history)

        repl = _bare_repl(self.store)
        repl._resume_session(sid)

        self.assertTrue(repl._session_active)
        self.assertEqual(repl._current_target, "192.0.2.5")
        self.assertEqual(repl._conversation_history, history)
        # the agent's own context is restored too (same object), so chat() has it
        self.assertIs(repl._agent.conversation_history, repl._conversation_history)
        self.assertEqual(self.store.get_session(sid)["status"], "active")

    def test_resume_unknown_session_is_noop(self):
        repl = _bare_repl(self.store)
        repl._resume_session("does-not-exist")
        self.assertFalse(repl._session_active)

    def test_continue_picks_most_recent(self):
        self.store.create_session(goal="old", target_focus="192.0.2.1")
        newest = self.store.create_session(goal="new", target_focus="192.0.2.2")
        repl = _bare_repl(self.store)
        repl._continue_last = True
        repl._apply_resume_request()
        self.assertTrue(repl._session_active)
        self.assertEqual(repl._current_target, "192.0.2.2")
        self.assertEqual(repl._tracker.session_id, newest)

    def test_continue_with_no_sessions_is_safe(self):
        repl = _bare_repl(self.store)
        repl._continue_last = True
        repl._apply_resume_request()
        self.assertFalse(repl._session_active)


if __name__ == "__main__":
    unittest.main()
