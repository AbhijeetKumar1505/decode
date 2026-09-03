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
