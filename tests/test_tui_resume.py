import asyncio
import contextlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decode.app.config import Config
from decode.hostcontrol import CommandPolicy, FilesystemScope, PermissionMode
from decode.models import (
    DataPolicy,
    ModelCost,
    ModelSpec,
    OpenRouterCatalogError,
    OpenRouterCatalogResult,
    default_model_registry,
)
from decode.persistence import SessionStore
from decode.persistence.evidence import EvidenceCollector
from decode.persistence.manager import SessionManager
from decode.schema import TaskState
from decode.schema.store import TaskStateStore
from decode.skills.registry import SkillRegistry
from decode.tui.app import AgentREPL


class _FakeAgent:
    provider_name = "openrouter"

    def __init__(self):
        self.conversation_history = []
        self.scope = None
        self.llm = mock.Mock(_model="z-ai/glm-5.2:free")

    def set_scope(self, entries):
        self.scope = list(entries)


def _bare_repl(store) -> AgentREPL:
    r = AgentREPL.__new__(AgentREPL)
    r._store = store
    r._sessions = SessionManager(store)
    r._agent = _FakeAgent()
    r._registry = SkillRegistry()
    r._model_registry = default_model_registry()
    r._openrouter_catalog_loaded = False
    r._openrouter_catalog_skipped = 0
    r._evidence = EvidenceCollector()
    r._scope_entries = []
    r._session_active = False
    r._tracker = None
    r._current_target = ""
    r._conversation_history = []
    r._resume_request = None
    r._continue_last = False
    return r


class TestModelCatalogue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = SessionStore(db_path=Path(self.tmp.name) / "decode.db")
        self.addCleanup(self.store.close)
        self.repl = _bare_repl(self.store)
        self.repl._thinking = lambda *args, **kwargs: contextlib.nullcontext()

    def _result(self):
        return OpenRouterCatalogResult(
            models=[
                ModelSpec(
                    id="openrouter/vendor/live-model",
                    provider="openrouter",
                    capabilities=["chat"],
                    data_policy=DataPolicy(),
                    context_limit=32000,
                    cost=ModelCost(pricing_version="openrouter-live"),
                )
            ],
            total_count=1,
        )

    def test_catalogue_is_fetched_once_and_can_be_refreshed(self):
        with mock.patch(
            "decode.models.fetch_openrouter_catalog", return_value=self._result()
        ) as fetch:
            self.assertTrue(self.repl._refresh_openrouter_catalog())
            self.assertTrue(self.repl._refresh_openrouter_catalog())
            self.assertTrue(self.repl._refresh_openrouter_catalog(force=True))
        self.assertEqual(fetch.call_count, 2)
        self.assertIsNotNone(
            self.repl._model_registry.get("openrouter/vendor/live-model")
        )
        self.assertIsNone(self.repl._model_registry.get("openrouter/z-ai/glm-5.2:free"))

    def test_failed_refresh_keeps_static_fallback(self):
        original = {model.id for model in self.repl._model_registry.all()}
        with (
            mock.patch(
                "decode.models.fetch_openrouter_catalog",
                side_effect=OpenRouterCatalogError("request failed"),
            ),
            mock.patch("decode.app.tui.app.console") as console,
        ):
            self.assertFalse(self.repl._refresh_openrouter_catalog())
        self.assertEqual(
            {model.id for model in self.repl._model_registry.all()}, original
        )
        console.print.assert_called_once()


class TestResumeFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self._decode_home = os.environ.get("DECODE_HOME")
        os.environ["DECODE_HOME"] = self.tmp.name
        Config.reload()
        self.addCleanup(self._restore_decode_home)
        self.addCleanup(os.chdir, self._cwd)
        self.store = SessionStore(db_path=Path(self.tmp.name) / "data" / "decode.db")
        self.addCleanup(self.store.close)

    def _save_conversation(self, sid, history):
        path = Config.MEMORY_PATH.parent / "sessions" / f"{sid}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(history), encoding="utf-8")

    def _restore_decode_home(self):
        if self._decode_home is None:
            os.environ.pop("DECODE_HOME", None)
        else:
            os.environ["DECODE_HOME"] = self._decode_home
        Config.reload()

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

    def test_agent_uses_matching_checkpoint_after_session_resume(self):
        sid = self.store.create_session(goal="inspect")
        states = TaskStateStore(self.store)
        state = TaskState(session_id=sid, objective="inspect")
        state.record_action("list_tools", {})
        state.record_observation("list_tools", {"success": True})
        states.save(state)

        repl = _bare_repl(self.store)
        repl._task_states = states
        repl._fs_scope = FilesystemScope(read_roots=[Path.cwd()])
        repl._cmd_policy = CommandPolicy()
        repl._perm_mode = PermissionMode.ASK
        repl._render_header_bar = lambda: None
        repl._mcp = lambda: None
        repl._host_approval = mock.AsyncMock(return_value=True)
        repl._meter_usage = lambda *args: (0, 0, 0.0)
        repl._record_run = lambda *args: None
        repl._agent.run_tool_loop = mock.AsyncMock(
            return_value={"final": "done", "steps": []}
        )
        with mock.patch("decode.app.tui.app.console"):
            repl._resume_session(sid)
            asyncio.run(repl._handle_agent("inspect"))
        kwargs = repl._agent.run_tool_loop.await_args.kwargs
        self.assertEqual(kwargs["session_id"], sid)
        self.assertEqual(len(kwargs["resume_state"].actions), 1)
        self.assertEqual(kwargs["resume_state"].objective, "inspect")
        self.assertEqual(kwargs["checkpoint"].__self__, states)


if __name__ == "__main__":
    unittest.main()
