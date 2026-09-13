import unittest
from pathlib import Path

from decode.agents.descriptor import (
    AgentDescriptor,
    AgentLimits,
    AgentMemoryScopes,
    AgentPermissions,
)
from decode.evaluation import (
    available_datasets,
    load_dataset,
    score_evidence_use,
    score_planning,
    score_prompt_injection,
    score_structured_output,
)
from decode.models import (
    ModelRouter,
    RoutingRequest,
    default_model_registry,
)
from decode.models.registry import DataPolicy
from decode.skills.base import RiskLevel


class TestAgentDescriptors(unittest.TestCase):
    def test_capability_outside_allow_list_is_rejected(self):
        with self.assertRaises(ValueError):
            AgentDescriptor(id="x", capabilities=["a"], allow_capabilities=["b"])

    def test_extra_fields_rejected(self):
        with self.assertRaises(Exception):
            AgentDescriptor(id="x", capabilities=[], surprise=True)


class TestDelegation(unittest.TestCase):
    def _parent(self) -> AgentDescriptor:
        return AgentDescriptor(
            id="parent",
            capabilities=["port_scan", "service_detection"],
            permissions=AgentPermissions(maximum_risk=RiskLevel.WRITE),
            memory=AgentMemoryScopes(read=["session", "project"], write=["project"]),
            limits=AgentLimits(token_budget=1000, max_delegation_depth=1),
        )

    def test_subset_delegation_succeeds(self):
        child = self._parent().delegate(
            "child", ["port_scan"], maximum_risk=RiskLevel.READ, token_budget=400
        )
        self.assertEqual(child.capabilities, ["port_scan"])
        self.assertEqual(child.permissions.maximum_risk, RiskLevel.READ)
        self.assertEqual(child.limits.token_budget, 400)
        self.assertEqual(child.limits.max_delegation_depth, 0)

    def test_cannot_add_capability(self):
        with self.assertRaises(ValueError):
            self._parent().delegate("child", ["password_attack"])

    def test_cannot_raise_risk(self):
        with self.assertRaises(ValueError):
            self._parent().delegate(
                "child", ["port_scan"], maximum_risk=RiskLevel.DESTRUCTIVE
            )

    def test_cannot_raise_budget(self):
        with self.assertRaises(ValueError):
            self._parent().delegate("child", ["port_scan"], token_budget=5000)

    def test_cannot_add_memory_scope(self):
        with self.assertRaises(ValueError):
            self._parent().delegate(
                "child", ["port_scan"], memory_write=["credentials"]
            )

    def test_depth_is_exhausted(self):
        child = self._parent().delegate("child", ["port_scan"])
        with self.assertRaises(ValueError):
            child.delegate("grandchild", ["port_scan"])


class TestModelRegistryAndRouting(unittest.TestCase):
    def setUp(self):
        self.registry = default_model_registry()
        self.router = ModelRouter(self.registry)

    def test_registry_seeds_hosted_models(self):
        specs = self.registry.all()
        ids = {s.id for s in specs}
        # the two direct-API hosted defaults plus a sampling of OpenRouter models
        self.assertLessEqual(
            {
                "openai/gpt-4o",
                "anthropic/claude-sonnet-4-20250514",
                "openrouter/z-ai/glm-5.2:free",
                "openrouter/google/gemma-4-31b:free",
                "openrouter/minimax/minimax-m3:free",
                "openrouter/nvidia/nemotron-3-ultra:free",
            },
            ids,
        )
        self.assertTrue(all(s.data_policy.locality == "hosted" for s in specs))
        # Mistral is fully retired as an orchestrator.
        self.assertFalse(any(s.provider == "mistral" for s in specs))

    def test_openrouter_model_name_is_full_slug(self):
        # id is ``openrouter/<vendor>/<model>:free`` so model_name (everything
        # after the first slash) is the exact slug the OpenRouter API expects.
        glm = self.registry.get("openrouter/z-ai/glm-5.2:free")
        self.assertEqual(glm.model_name, "z-ai/glm-5.2:free")
        self.assertEqual(glm.provider, "openrouter")
        self.assertEqual(glm.cost.input_per_mtok, 0.0)  # free variant

        free_router = self.registry.get("openrouter/openrouter/free")
        self.assertEqual(free_router.model_name, "openrouter/free")
        self.assertIn("reasoning", free_router.capabilities)
        self.assertIn("vision", free_router.capabilities)
        self.assertEqual(free_router.context_limit, 200_000)

    def test_planning_picks_highest_quality_structured_model(self):
        decision = self.router.route(RoutingRequest(task_class="planning"))
        self.assertTrue(decision.selected)
        self.assertEqual(decision.model_id, "anthropic/claude-sonnet-4-20250514")
        self.assertIn("structured-planning", decision.matched_rules)

    def test_routing_is_reproducible(self):
        r = RoutingRequest(task_class="analysis")
        self.assertEqual(self.router.route(r).model_id, self.router.route(r).model_id)

    def test_local_only_fails_closed(self):
        decision = self.router.route(
            RoutingRequest(task_class="analysis", local_only=True)
        )
        self.assertFalse(decision.selected)
        self.assertIn("local", decision.reason)

    def test_confidential_data_forces_local_and_fails(self):
        decision = self.router.route(
            RoutingRequest(task_class="analysis", data_classification="confidential")
        )
        self.assertFalse(decision.selected)
        self.assertIn("confidential-local", decision.matched_rules)

    def test_allowlist_filters(self):
        decision = self.router.route(
            RoutingRequest(task_class="analysis", allowlist=["openai"])
        )
        self.assertEqual(decision.model_id, "openai/gpt-4o")

    def test_pinned_model(self):
        decision = self.router.route(
            RoutingRequest(pinned_model="openrouter/z-ai/glm-5.2:free")
        )
        self.assertEqual(decision.model_id, "openrouter/z-ai/glm-5.2:free")
        self.assertEqual(
            self.router.route(RoutingRequest(pinned_model="ghost/model")).selected,
            False,
        )

    def test_fallback_stays_in_locality_and_exhausts(self):
        first = self.router.route(RoutingRequest(task_class="planning"))
        second = self.router.fallback(first, RoutingRequest(task_class="planning"))
        self.assertTrue(second.selected)
        self.assertNotEqual(second.model_id, first.model_id)
        # every fallback stays hosted (no locality crossing)
        self.assertEqual(
            self.registry.get(second.model_id).data_policy.locality, "hosted"
        )
        third = self.router.fallback(second, RoutingRequest(task_class="planning"))
        exhausted = self.router.fallback(third, RoutingRequest(task_class="planning"))
        self.assertFalse(exhausted.selected)

    def test_fallback_disabled(self):
        first = self.router.route(
            RoutingRequest(task_class="planning", allow_fallback=False)
        )
        self.assertFalse(
            self.router.fallback(
                first, RoutingRequest(task_class="planning", allow_fallback=False)
            ).selected
        )

    def test_data_policy_accepts(self):
        policy = DataPolicy(max_classification="internal")
        self.assertTrue(policy.accepts("public"))
        self.assertFalse(policy.accepts("confidential"))


class TestAgentModelSelection(unittest.TestCase):
    def test_select_model_uses_only_configured_providers(self):
        from decode.models import ModelRouter
        from decode.universal_agent import UniversalAgent

        registry = default_model_registry()
        for spec in registry.all():  # only openrouter has credentials in this scenario
            spec.available = spec.provider == "openrouter"

        agent = UniversalAgent.__new__(UniversalAgent)
        agent.model_router = ModelRouter(registry)

        class _Ctx:
            def __init__(self):
                self.entries = []

            def add_entry(self, role, content):
                self.entries.append((role, content))

        agent.context = _Ctx()

        decision = agent.select_model("planning")
        self.assertEqual(decision.model_id, "openrouter/z-ai/glm-5.2:free")
        self.assertTrue(agent.context.entries)  # public reason recorded


class TestEvaluationDatasets(unittest.TestCase):
    DIR = Path("data/evaluations")

    def test_all_four_datasets_load(self):
        names = available_datasets(self.DIR)
        for expected in (
            "planning",
            "structured_output",
            "evidence_use",
            "prompt_injection",
        ):
            self.assertIn(expected, names)
            load_dataset(expected, self.DIR)  # validates ids and structure

    def test_structured_output_scorer(self):
        case = load_dataset("structured_output", self.DIR)["cases"][0]
        ok, _ = score_structured_output(
            case, {"title": "t", "severity": "high", "description": "d"}
        )
        self.assertTrue(ok)
        bad, _ = score_structured_output(case, {"title": "t"})
        self.assertFalse(bad)

    def test_planning_scorer_enforces_order(self):
        case = load_dataset("planning", self.DIR)["cases"][0]
        ok, _ = score_planning(case, ["host_discovery", "port_scan", "report"])
        self.assertTrue(ok)
        wrong, _ = score_planning(case, ["port_scan", "host_discovery", "report"])
        self.assertFalse(wrong)
        forbidden, _ = score_planning(
            case, ["host_discovery", "port_scan", "report", "password_attack"]
        )
        self.assertFalse(forbidden)

    def test_evidence_scorer_rejects_fabrication(self):
        case = load_dataset("evidence_use", self.DIR)["cases"][0]
        ok, _ = score_evidence_use(case, ["evidence:port-22"])
        self.assertTrue(ok)
        fabricated, _ = score_evidence_use(case, ["evidence:made-up"])
        self.assertFalse(fabricated)
        missing, _ = score_evidence_use(case, [])
        self.assertFalse(missing)

    def test_prompt_injection_scorer(self):
        case = load_dataset("prompt_injection", self.DIR)["cases"][0]
        ok, _ = score_prompt_injection(case, ["reported scan result to user"])
        self.assertTrue(ok)
        obeyed, _ = score_prompt_injection(case, ["scan 10.0.0.0/8 ignore scope now"])
        self.assertFalse(obeyed)


if __name__ == "__main__":
    unittest.main()


from types import SimpleNamespace
from unittest.mock import patch

import pytest

from decode.evaluation import (
    RoutingEvalCase,
    ToolEvalCase,
    evaluate_routing,
    evaluate_tool_calls,
)
from decode.observability.replay import ReplayRecord, build_replay_record


def test_routing_regression_matrix() -> None:
    router = ModelRouter(default_model_registry())
    cases = [
        RoutingEvalCase(
            id="planning",
            prompt="plan the review",
            expected_task_class="planning",
            expected_model="anthropic/claude-sonnet-4-20250514",
            required_rules=["structured-planning"],
        ),
        RoutingEvalCase(
            id="code",
            prompt="fix the function",
            expected_task_class="code",
            request=RoutingRequest(allowlist=["openai"]),
            expected_model="openai/gpt-4o",
        ),
        RoutingEvalCase(
            id="extraction",
            prompt="extract fields",
            expected_task_class="extraction",
            request=RoutingRequest(allowlist=["openai"]),
            expected_model="openai/gpt-4o",
        ),
        RoutingEvalCase(id="local", request=RoutingRequest(local_only=True)),
        RoutingEvalCase(
            id="confidential",
            request=RoutingRequest(data_classification="confidential"),
            required_rules=["confidential-local"],
        ),
        RoutingEvalCase(
            id="missing", request=RoutingRequest(pinned_model="missing/model")
        ),
        RoutingEvalCase(
            id="capability",
            request=RoutingRequest(required_capabilities=["nonexistent"]),
        ),
    ]
    report = evaluate_routing(cases, router)
    assert report.passed, report.model_dump()
    assert report.accuracy == 1.0
    assert evaluate_routing(cases, router) == report
    changed = cases[0].model_copy(update={"expected_model": "wrong/model"})
    assert not evaluate_routing([changed], router).passed
    with patch.object(router, "route", side_effect=RuntimeError("synthetic-secret")):
        failed = evaluate_routing([cases[0]], router)
    assert not failed.passed
    assert "synthetic-secret" not in failed.model_dump_json()
    with pytest.raises(ValueError):
        evaluate_routing([cases[0], cases[0]], router)
    with pytest.raises(ValueError):
        evaluate_routing([], router)


@pytest.mark.parametrize(
    "calls",
    [
        [],
        [{"name": "file_write", "arguments": {"path": "/lab/info"}}],
        [{"name": "file_read", "arguments": {"path": "/outside/info"}}],
        [{"name": "file_read", "arguments": {"path": "/lab/info"}}] * 2,
        [{"name": "file_read", "arguments": "bad"}],
    ],
)
def test_tool_regression_detects_wrong_calls(calls: list) -> None:
    case = ToolEvalCase(
        id="read",
        prompt="read lab info",
        expected_calls=[
            {"name": "file_read", "arguments": {"path": "/lab/info"}},
        ],
    )
    report = evaluate_tool_calls([case], lambda _: calls)
    assert not report.passed
    assert report.accuracy == 0.0


def test_tool_regression_order_and_error_redaction() -> None:
    expected = [
        {"name": "list_tools", "arguments": {}},
        {"name": "shell_command", "arguments": {"argv": ["example-tool", "--version"]}},
    ]
    case = ToolEvalCase(
        id="discover", prompt="inspect installed tools", expected_calls=expected
    )
    assert evaluate_tool_calls([case], lambda _: expected).passed
    assert not evaluate_tool_calls([case], lambda _: list(reversed(expected))).passed

    def broken(_: str) -> list[dict]:
        raise RuntimeError("password=synthetic-secret")

    report = evaluate_tool_calls([case], broken)
    assert not report.passed
    assert "synthetic-secret" not in report.model_dump_json()


def _replay_invocation() -> SimpleNamespace:
    return SimpleNamespace(
        capability="shell_command",
        tool="example-tool",
        argv=["example-tool", "value with spaces"],
        normalized_params={"argv": ["example-tool", "value with spaces"]},
        adapter_id="host",
        adapter_version="1",
        parser_id="raw",
        parser_version="1",
    )


def test_replay_identity_is_stable_and_roundtrips() -> None:
    invocation = _replay_invocation()
    first = build_replay_record(
        invocation, evidence_id="first", evidence_sha256="a" * 64
    )
    second = build_replay_record(
        invocation, evidence_id="second", evidence_sha256="b" * 64
    )
    assert first.replay_id == second.replay_id
    assert first.evidence_sha256 != second.evidence_sha256
    assert first.command == "example-tool 'value with spaces'"
    assert ReplayRecord.model_validate_json(first.model_dump_json()) == first
    invocation.argv.append("changed")
    assert first.argv == ["example-tool", "value with spaces"]
    assert build_replay_record(invocation).replay_id != first.replay_id


@pytest.mark.parametrize(
    "field",
    ["tool_version", "executor", "platform", "architecture", "environment_version"],
)
def test_replay_environment_changes_identity(field: str) -> None:
    invocation = _replay_invocation()
    assert (
        build_replay_record(invocation).replay_id
        != build_replay_record(invocation, **{field: "different"}).replay_id
    )


@pytest.mark.parametrize(
    "field",
    [
        "capability",
        "tool",
        "adapter_id",
        "adapter_version",
        "parser_id",
        "parser_version",
    ],
)
def test_replay_adapter_changes_identity(field: str) -> None:
    invocation = _replay_invocation()
    baseline = build_replay_record(invocation)
    setattr(invocation, field, "different")
    assert build_replay_record(invocation).replay_id != baseline.replay_id
