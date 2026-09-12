"""Token → cost estimation and provider cumulative token accounting."""

import unittest

from decode.kernel.provider import LLMProvider
from decode.models import default_model_registry, estimate_cost, estimate_cost_for
from decode.models.registry import ModelCost


class _Usage:
    def __init__(self, prompt_tokens=0, completion_tokens=0):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _StubProvider(LLMProvider):
    async def complete(self, prompt, system=None):
        return ""

    async def chat(self, messages):
        return ""

    @property
    def name(self):
        return "stub"


class EstimateCostTest(unittest.TestCase):
    def test_estimate_cost_splits_input_and_output(self):
        cost = ModelCost(input_per_mtok=2.5, output_per_mtok=10.0)
        # 1M prompt @2.5 + 0.5M completion @10.0 = 2.5 + 5.0
        self.assertAlmostEqual(estimate_cost(cost, 1_000_000, 500_000), 7.5)

    def test_free_model_is_zero(self):
        self.assertEqual(estimate_cost(ModelCost(), 5000, 5000), 0.0)

    def test_estimate_cost_for_registry_lookup(self):
        reg = default_model_registry()
        # exact provider-prefixed id
        self.assertAlmostEqual(
            estimate_cost_for(reg, "openai/gpt-4o", 1_000_000, 0), 2.5
        )
        # bare slug matches openrouter/<slug> and is a free model -> 0.0
        self.assertEqual(
            estimate_cost_for(reg, "z-ai/glm-5.2:free", 1_000_000, 1_000_000), 0.0
        )
        # unknown model -> 0.0, never raises
        self.assertEqual(estimate_cost_for(reg, "no/such-model", 10, 10), 0.0)


class ProviderUsageAccountingTest(unittest.TestCase):
    def test_record_usage_accumulates_split(self):
        provider = _StubProvider()
        provider._record_usage(_Usage(prompt_tokens=100, completion_tokens=40))
        provider._record_usage(_Usage(prompt_tokens=60, completion_tokens=10))

        self.assertEqual(provider.session_prompt_tokens, 160)
        self.assertEqual(provider.session_completion_tokens, 50)
        self.assertEqual(provider.session_tokens, 210)


if __name__ == "__main__":
    unittest.main()
