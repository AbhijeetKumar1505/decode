import unittest
from unittest import mock

from decode.models import ModelGateway, ModelRegistry
from decode.models.registry import DataPolicy, ModelSpec


def _registry():
    return ModelRegistry(
        [
            ModelSpec(
                id="openrouter/z-ai/glm-5.2:free",
                provider="openrouter",
                capabilities=["chat", "structured_output", "tools"],
                data_policy=DataPolicy(
                    max_classification="internal", locality="hosted"
                ),
                quality_scores={"planning": 0.88, "analysis": 0.88, "code": 0.6},
                available=True,
                fallback_group="g",
            ),
            ModelSpec(
                id="openrouter/poolside/laguna-s-2.1:free",
                provider="openrouter",
                capabilities=["chat", "structured_output", "tools", "code"],
                data_policy=DataPolicy(
                    max_classification="internal", locality="hosted"
                ),
                quality_scores={"planning": 0.79, "analysis": 0.78, "code": 0.9},
                available=True,
                fallback_group="g",
            ),
        ]
    )


class TestModelGateway(unittest.TestCase):
    def setUp(self):
        # Clear any per-role / routing env for a clean default.
        self._env = mock.patch.dict(
            "os.environ",
            {
                "DECODE_PLANNER_MODEL": "",
                "DECODE_WORKER_MODEL": "",
                "DECODE_REVIEWER_MODEL": "",
                "DECODE_CODER_MODEL": "",
                "DECODE_MODEL_ROUTING": "",
            },
            clear=False,
        )
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def test_default_single_model_resolves_to_config(self):
        from decode.config import Config

        gw = ModelGateway(_registry(), routing_enabled=False)
        self.assertEqual(gw.resolve_spec("worker"), (Config.PROVIDER, Config.MODEL))

    def test_registered_default_returns_same_instance(self):
        from decode.config import Config

        gw = ModelGateway(_registry(), routing_enabled=False)
        sentinel = mock.Mock()
        gw.register(Config.PROVIDER, Config.MODEL, sentinel)
        self.assertIs(gw.for_role("worker"), sentinel)

    def test_per_role_override_from_registry(self):
        gw = ModelGateway(_registry(), routing_enabled=False)
        with mock.patch.dict(
            "os.environ",
            {"DECODE_CODER_MODEL": "openrouter/poolside/laguna-s-2.1:free"},
        ):
            self.assertEqual(
                gw.resolve_spec("coder"), ("openrouter", "poolside/laguna-s-2.1:free")
            )

    def test_override_provider_slash_model(self):
        gw = ModelGateway(_registry(), routing_enabled=False)
        with mock.patch.dict(
            "os.environ", {"DECODE_WORKER_MODEL": "openai/gpt-4o-mini"}
        ):
            self.assertEqual(gw.resolve_spec("worker"), ("openai", "gpt-4o-mini"))

    def test_routing_opt_in_picks_by_task_class(self):
        gw = ModelGateway(_registry(), routing_enabled=True)
        # coder -> "code" task class; the code-capable model wins by quality
        self.assertEqual(
            gw.resolve_spec("coder"), ("openrouter", "poolside/laguna-s-2.1:free")
        )
        # planner -> "planning"; the higher planning score wins
        self.assertEqual(
            gw.resolve_spec("planner"), ("openrouter", "z-ai/glm-5.2:free")
        )

    def test_route_for_role_is_reproducible(self):
        gw = ModelGateway(_registry(), routing_enabled=True)
        d1 = gw.route_for_role("planner")
        d2 = gw.route_for_role("planner")
        self.assertEqual(d1.model_id, d2.model_id)
        self.assertTrue(d1.selected)


if __name__ == "__main__":
    unittest.main()
