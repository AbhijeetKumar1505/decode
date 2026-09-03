import ast
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decode.audit import AuditLayer
from decode.config import Config
from decode.feedback import FeedbackStore
from decode.kernel.safety import Permission, SafetyController
from decode.logging_service import LoggingService
from decode.skills.base import RiskLevel, SkillCategory, SkillSpec
from decode.utils import parse_llm_response


class TestSafetyInvariants(unittest.TestCase):
    """The risk gate is the core safety control; these invariants must hold."""

    def setUp(self):
        self.safety = SafetyController()

    def _check(self, risk, **kwargs):
        controller = kwargs.pop("controller", self.safety)
        return asyncio.run(controller.check("some_skill", risk, {}))

    def test_read_is_auto_allowed(self):
        self.assertEqual(self._check(RiskLevel.READ), Permission.ALLOW)

    def test_destructive_is_denied_by_default(self):
        self.assertEqual(self._check(RiskLevel.DESTRUCTIVE), Permission.DENY)

    def test_write_requires_approval_without_callback(self):
        self.assertEqual(self._check(RiskLevel.WRITE), Permission.REQUIRE_APPROVAL)

    def test_write_allowed_when_callback_approves(self):
        async def approve(name, params):
            return True

        controller = SafetyController(approval_callback=approve)
        self.assertEqual(
            self._check(RiskLevel.WRITE, controller=controller), Permission.ALLOW
        )

    def test_write_denied_when_callback_rejects(self):
        async def reject(name, params):
            return False

        controller = SafetyController(approval_callback=reject)
        self.assertEqual(
            self._check(RiskLevel.WRITE, controller=controller), Permission.DENY
        )

    def test_prohibited_action_is_denied(self):
        self.safety.prohibit("some_skill")
        self.assertEqual(self._check(RiskLevel.READ), Permission.DENY)

    def test_override_rule_is_respected(self):
        self.safety.set_override("some_skill", Permission.DENY)
        self.assertEqual(self._check(RiskLevel.READ), Permission.DENY)


class TestAuditTrail(unittest.TestCase):
    """Every execution must be auditable; the trail must be written and queryable."""

    def test_execution_is_recorded_and_queryable(self):
        with tempfile.TemporaryDirectory() as d:
            audit = AuditLayer(base_path=Path(d))
            audit.record_execution(
                tool="shell", target="echo hi", risk="WRITE", approved=True, detail="ok"
            )
            audit.record_execution(
                tool="nmap_pro", risk="WRITE", approved=True, detail="2 ports"
            )
            rows = audit.query()
            self.assertEqual(len(rows), 2)
            self.assertEqual({r.tool for r in rows}, {"shell", "nmap_pro"})
            self.assertTrue(all(r.event == "tool_execution" for r in rows))


class TestParseLLMResponse(unittest.TestCase):
    def test_extracts_embedded_json(self):
        parsed = parse_llm_response(
            'prose {"action": "nmap_pro", "params": {}} trailing'
        )
        self.assertEqual(parsed["action"], "nmap_pro")

    def test_falls_back_on_invalid_json(self):
        parsed = parse_llm_response("no json here")
        # No spurious action to execute, and the raw text is preserved as the message.
        self.assertIsNone(parsed["action"])
        self.assertIn("no json here", parsed["message"])
        self.assertNotIn("thought", parsed)


class _ChainStore:
    def get_session(self, session_id):
        return {"id": session_id, "target_focus": "192.0.2.10"}


class _ChainTracker:
    session_id = "session-id"
    target_id = "database-target-id"
    store = _ChainStore()

    def get_open_ports_summary(self):
        return []

    def record_evidence(self, **kwargs):
        return "evidence-id"

    def record_finding(self, finding):
        return "finding-id"

    def record_port(self, **kwargs):
        return "port-id"


def _heavy_deps_available():
    try:
        import faiss  # noqa: F401
        import openai  # noqa: F401

        return True
    except ImportError:
        return False


@unittest.skipUnless(_heavy_deps_available(), "requires faiss + openai")
class TestUniversalAgentExecutionPath(unittest.TestCase):
    """End-to-end execution wiring: audit records written, DESTRUCTIVE skills denied."""

    def _build_agent(self, tmp):
        import decode.universal_agent as ua

        class _FakeSkill:
            def __init__(self, risk):
                self.spec = SkillSpec(
                    name="fake_skill",
                    description="Test execution skill",
                    category=SkillCategory.RECONNAISSANCE,
                    risk_level=risk,
                    target_required=False,
                )

            async def execute(self, **kwargs):
                return {"ok": True}

        self._fake_read_skill = _FakeSkill(RiskLevel.READ)
        self._fake_destructive_skill = _FakeSkill(RiskLevel.DESTRUCTIVE)

        fake_registry = mock.Mock()
        fake_registry.get.side_effect = lambda name: {
            "read_skill": self._fake_read_skill,
            "destructive_skill": self._fake_destructive_skill,
        }.get(name)

        with (
            mock.patch.object(ua.Config, "validate", return_value=None),
            mock.patch.object(ua, "create_provider", return_value=mock.Mock()),
            mock.patch.object(ua, "SelfLearningMemory", return_value=mock.Mock()),
            mock.patch.object(ua, "SkillRegistry", return_value=fake_registry),
        ):
            agent = ua.UniversalAgent(provider="openrouter")
        agent.audit = AuditLayer(base_path=tmp / "audit")
        agent.logging = LoggingService(base_path=tmp / "logs")
        agent.feedback = FeedbackStore(base_path=tmp / "feedback")
        agent.set_scope([])
        return agent

    def test_raw_command_execution_is_blocked_and_audited(self):
        with tempfile.TemporaryDirectory() as d:
            agent = self._build_agent(Path(d))
            result = asyncio.run(agent.execute_command("echo hello"))
            self.assertFalse(result.success)
            self.assertIn("disabled", result.error)
            rows = agent.audit.query()
            self.assertTrue(
                any(
                    row.tool == "raw_shell_command" and row.event == "rejection"
                    for row in rows
                )
            )

    def test_destructive_skill_is_denied_and_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            agent = self._build_agent(Path(d))
            result = asyncio.run(
                agent.execute_registered_skill("destructive_skill", {})
            )
            self.assertFalse(result.success)
            rows = agent.audit.query()
            self.assertTrue(any(r.event == "rejection" for r in rows))


class TestCliGovernedDomainEntryPoints(unittest.TestCase):
    def _tree(self) -> ast.Module:
        cli_path = Path(__file__).parents[1] / "decode" / "cli.py"
        return ast.parse(cli_path.read_text(encoding="utf-8"))

    def test_cli_has_no_direct_domain_module_imports(self) -> None:
        imports = [
            node.module
            for node in ast.walk(self._tree())
            if isinstance(node, ast.ImportFrom)
            and node.module
            and (node.module == "modules" or node.module.startswith("modules."))
        ]

        self.assertEqual(imports, [])


class TestProviderConfiguration(unittest.TestCase):
    def test_provider_key_names_are_provider_specific(self) -> None:
        self.assertEqual(Config.provider_key_name("openrouter"), "OPENROUTER_API_KEY")
        self.assertEqual(Config.provider_key_name("openai"), "OPENAI_API_KEY")
        self.assertEqual(Config.provider_key_name("anthropic"), "ANTHROPIC_API_KEY")

    def test_selected_provider_uses_matching_credential(self) -> None:
        with mock.patch.object(Config, "OPENAI_API_KEY", "configured"):
            self.assertTrue(Config.has_provider_credentials("openai"))
        with mock.patch.object(Config, "OPENAI_API_KEY", None):
            self.assertFalse(Config.has_provider_credentials("openai"))

    def test_unknown_provider_fails_fast(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown provider"):
            Config.provider_key_name("unsupported")


class TestOpenRouterRetry(unittest.TestCase):
    """Transient upstream 429s from the shared free pool must be retried, not fatal."""

    def _provider(self, client):
        from decode.kernel.provider import OpenRouterProvider

        p = OpenRouterProvider.__new__(OpenRouterProvider)
        p._model = "z-ai/glm-5.2:free"
        p._client = client
        return p

    def _err(self, status):
        exc = RuntimeError("Provider returned error")
        exc.status_code = status
        exc.response = None
        return exc

    def test_retries_then_succeeds(self):
        calls = {"n": 0}

        class _Msg:
            content = "ok"

        class _Client:
            class chat:
                class completions:
                    @staticmethod
                    def create(**_kwargs):
                        calls["n"] += 1
                        if calls["n"] < 3:
                            exc = RuntimeError("429")
                            exc.status_code = 429
                            exc.response = None
                            raise exc
                        return mock.Mock(choices=[mock.Mock(message=_Msg())])

        provider = self._provider(_Client())
        with mock.patch("asyncio.sleep", new=_async_noop):
            result = asyncio.run(provider.chat([{"role": "user", "content": "hi"}]))
        self.assertEqual(result, "ok")
        self.assertEqual(calls["n"], 3)

    def test_non_retryable_status_raises_immediately(self):
        class _Client:
            class chat:
                class completions:
                    @staticmethod
                    def create(**_kwargs):
                        exc = RuntimeError("bad request")
                        exc.status_code = 400
                        exc.response = None
                        raise exc

        provider = self._provider(_Client())
        with self.assertRaises(RuntimeError):
            asyncio.run(provider.chat([{"role": "user", "content": "hi"}]))

    def test_retry_delay_prefers_retry_after_header(self):
        from decode.kernel.provider import OpenRouterProvider

        exc = RuntimeError("429")
        exc.response = mock.Mock(headers={"Retry-After": "5"})
        self.assertEqual(OpenRouterProvider._retry_delay(exc, attempt=0), 5.0)
        # No header → exponential backoff capped at 8s.
        self.assertEqual(
            OpenRouterProvider._retry_delay(RuntimeError(), attempt=1), 2.0
        )


class TestUsageAccounting(unittest.TestCase):
    """Providers accumulate token usage for the TUI's top bar and streaming meter."""

    def _provider(self, client):
        from decode.kernel.provider import OpenRouterProvider

        p = OpenRouterProvider.__new__(OpenRouterProvider)
        p.last_prompt_tokens = 0
        p.last_completion_tokens = 0
        p.session_tokens = 0
        p._model = "z-ai/glm-5.2:free"
        p._client = client
        return p

    def test_session_tokens_accumulate_across_calls(self):
        class _Usage:
            prompt_tokens = 10
            completion_tokens = 5

        class _Client:
            class chat:
                class completions:
                    @staticmethod
                    def create(**_kwargs):
                        return mock.Mock(
                            choices=[mock.Mock(message=mock.Mock(content="hi"))],
                            usage=_Usage(),
                        )

        provider = self._provider(_Client())
        asyncio.run(provider.chat([{"role": "user", "content": "a"}]))
        asyncio.run(provider.chat([{"role": "user", "content": "b"}]))
        self.assertEqual(provider.last_prompt_tokens, 10)
        self.assertEqual(provider.last_completion_tokens, 5)
        self.assertEqual(provider.session_tokens, 30)  # (10+5) × 2

    def test_record_usage_handles_anthropic_shape(self):
        class _AnthropicUsage:  # no prompt_tokens/completion_tokens → fallback path
            input_tokens = 7
            output_tokens = 3

        provider = self._provider(client=None)
        provider._record_usage(_AnthropicUsage())
        self.assertEqual(provider.session_tokens, 10)

    def test_record_usage_tolerates_missing_usage(self):
        provider = self._provider(client=None)
        provider._record_usage(None)
        self.assertEqual(provider.session_tokens, 0)


async def _async_noop(*_args, **_kwargs):
    return None


if __name__ == "__main__":
    unittest.main()
