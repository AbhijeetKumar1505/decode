"""Tests for the Mistral and Bedrock provider adapters + create_provider wiring."""

import asyncio
import unittest

from decode.kernel.provider import (
    BedrockProvider,
    MistralProvider,
    create_provider,
)
from decode.models import (
    OpenRouterCatalogError,
    default_model_registry,
    fetch_openrouter_catalog,
    registry_with_openrouter_catalog,
)


class CreateProviderTest(unittest.TestCase):
    def test_registers_new_providers(self):
        self.assertIsInstance(create_provider("mistral"), MistralProvider)
        self.assertIsInstance(create_provider("bedrock"), BedrockProvider)

    def test_unknown_provider_raises(self):
        with self.assertRaises(ValueError):
            create_provider("nope")

    def test_registry_has_bedrock_spec(self):
        # Bedrock is registered; Mistral ships only as an opt-in adapter (it is
        # intentionally retired from the default catalogue — see test_p4).
        reg = default_model_registry()
        bedrock = reg.get("bedrock/anthropic.claude-3-5-sonnet-20240620-v1:0")
        self.assertIsNotNone(bedrock)
        self.assertEqual(bedrock.provider, "bedrock")
        self.assertFalse(any(s.provider == "mistral" for s in reg.all()))


class _CatalogResponse:
    def __init__(self, payload, error=None):
        self._payload = payload
        self._error = error

    def raise_for_status(self):
        if self._error is not None:
            raise self._error

    def json(self):
        return self._payload


class OpenRouterCatalogTest(unittest.TestCase):
    def _fetch(self, payload, api_key=""):
        calls = []

        def get(url, **kwargs):
            calls.append((url, kwargs))
            return _CatalogResponse(payload)

        return fetch_openrouter_catalog(api_key, http_get=get), calls

    def test_fetches_all_modalities_and_maps_metadata(self):
        result, calls = self._fetch(
            {
                "data": [
                    {
                        "id": "vendor/multimodal",
                        "context_length": 65536,
                        "architecture": {
                            "input_modalities": ["text", "image", "file"],
                            "output_modalities": ["text", "audio"],
                        },
                        "pricing": {
                            "prompt": "0.0000025",
                            "completion": "0.00001",
                        },
                        "supported_parameters": [
                            "tools",
                            "structured_outputs",
                            "reasoning",
                        ],
                    },
                    {
                        "id": "vendor/embed",
                        "architecture": {"output_modalities": ["embeddings"]},
                        "pricing": {"prompt": "0", "completion": "0"},
                    },
                    {
                        "id": "vendor/image",
                        "architecture": {"output_modalities": ["image"]},
                        "pricing": {"prompt": 0, "completion": 0},
                    },
                    {"id": "vendor/bad-price", "pricing": {"prompt": "nan"}},
                ]
            },
            api_key="test-key",
        )
        self.assertEqual(result.total_count, 4)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(len(result.models), 3)
        multimodal = next(
            model for model in result.models if model.model_name == "vendor/multimodal"
        )
        self.assertEqual(multimodal.context_limit, 65536)
        self.assertEqual(multimodal.cost.input_per_mtok, 2.5)
        self.assertEqual(multimodal.cost.output_per_mtok, 10.0)
        self.assertLessEqual(
            {
                "audio",
                "chat",
                "file",
                "long_context",
                "reasoning",
                "structured_output",
                "tools",
                "vision",
            },
            set(multimodal.capabilities),
        )
        self.assertEqual(calls[0][0], "https://openrouter.ai/api/v1/models")
        self.assertEqual(calls[0][1]["params"], {"output_modalities": "all"})
        self.assertEqual(calls[0][1]["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(calls[0][1]["timeout"], 10.0)

    def test_curated_quality_and_code_metadata_are_preserved(self):
        result, _ = self._fetch(
            {
                "data": [
                    {
                        "id": "poolside/laguna-s-2.1:free",
                        "context_length": 64000,
                        "architecture": {"output_modalities": ["text"]},
                        "pricing": {"prompt": "0", "completion": "0"},
                    }
                ]
            }
        )
        model = result.models[0]
        self.assertIn("code", model.capabilities)
        self.assertGreater(model.quality_for("code"), 0)
        self.assertEqual(model.context_limit, 64000)

    def test_zero_context_and_unavailable_pricing_remain_in_catalog(self):
        result, _ = self._fetch(
            {
                "data": [
                    {
                        "id": "vendor/non-token-model",
                        "context_length": 0,
                        "architecture": {"output_modalities": ["image"]},
                        "pricing": {"prompt": "-1", "completion": "-1"},
                    }
                ]
            }
        )
        self.assertEqual(result.skipped, 0)
        self.assertEqual(result.models[0].context_limit, 8192)
        self.assertEqual(result.models[0].cost.input_per_mtok, 0)
        self.assertEqual(
            result.models[0].cost.pricing_version, "openrouter-live-unavailable"
        )

    def test_registry_replaces_only_openrouter_fallback_models(self):
        result, _ = self._fetch(
            {
                "data": [
                    {
                        "id": "vendor/new",
                        "architecture": {"output_modalities": ["text"]},
                        "pricing": {},
                    }
                ]
            }
        )
        registry = registry_with_openrouter_catalog(result)
        self.assertIsNotNone(registry.get("openrouter/vendor/new"))
        self.assertIsNone(registry.get("openrouter/z-ai/glm-5.2:free"))
        self.assertIsNotNone(registry.get("openai/gpt-4o"))

    def test_public_fetch_omits_authorization_without_a_key(self):
        result, calls = self._fetch(
            {
                "data": [
                    {
                        "id": "vendor/public",
                        "architecture": {"output_modalities": ["text"]},
                        "pricing": {},
                    }
                ]
            }
        )
        self.assertEqual(len(result.models), 1)
        self.assertNotIn("Authorization", calls[0][1]["headers"])

    def test_invalid_records_and_duplicates_are_partial(self):
        valid = {
            "id": "vendor/model",
            "architecture": {"output_modalities": ["text"]},
            "pricing": {},
        }
        result, _ = self._fetch({"data": [valid, valid, None, {"id": ""}]})
        self.assertEqual(len(result.models), 1)
        self.assertEqual(result.skipped, 3)

    def test_invalid_or_empty_response_fails_closed(self):
        for payload in ({}, {"data": "wrong"}, {"data": []}, {"data": [None]}):
            with self.subTest(payload=payload):
                with self.assertRaises(OpenRouterCatalogError):
                    self._fetch(payload)

    def test_request_failure_does_not_copy_exception_detail(self):
        def get(*args, **kwargs):
            return _CatalogResponse({}, RuntimeError("token=synthetic-secret"))

        with self.assertRaises(OpenRouterCatalogError) as caught:
            fetch_openrouter_catalog("synthetic-secret", http_get=get)
        self.assertNotIn("synthetic-secret", str(caught.exception))

    def test_timeout_is_bounded_before_network_access(self):
        for timeout in (0, -1, 61, float("inf"), True):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    fetch_openrouter_catalog(timeout=timeout, http_get=self.fail)


class _FakeMistralResponse:
    class _Choice:
        class _Msg:
            content = "mistral says hi"

        message = _Msg()

    choices = [_Choice()]

    class usage:  # OpenAI-shaped
        prompt_tokens = 12
        completion_tokens = 5


class _FakeMistralClient:
    class chat:
        @staticmethod
        def complete(model, messages, temperature=0.1):
            return _FakeMistralResponse()


class MistralProviderTest(unittest.TestCase):
    def test_unconfigured_without_key(self):
        provider = MistralProvider(api_key="")
        self.assertIsNone(provider._client)
        out = asyncio.run(provider.chat([{"role": "user", "content": "hi"}]))
        self.assertIn("not configured", out)

    def test_records_usage_with_fake_client(self):
        provider = MistralProvider(api_key="x")
        provider._client = _FakeMistralClient()
        out = asyncio.run(provider.complete("hello", system="be terse"))
        self.assertEqual(out, "mistral says hi")
        self.assertEqual(provider.session_prompt_tokens, 12)
        self.assertEqual(provider.session_completion_tokens, 5)


class _FakeBedrockClient:
    def converse(self, **kwargs):
        self.last_kwargs = kwargs
        return {
            "output": {"message": {"content": [{"text": "bedrock says hi"}]}},
            "usage": {"inputTokens": 20, "outputTokens": 8},
        }


class BedrockProviderTest(unittest.TestCase):
    def test_unconfigured_without_client(self):
        provider = BedrockProvider()
        provider._client = None
        out = asyncio.run(provider.chat([{"role": "user", "content": "hi"}]))
        self.assertIn("not configured", out)

    def test_converse_maps_messages_and_usage(self):
        provider = BedrockProvider()
        provider._client = _FakeBedrockClient()
        out = asyncio.run(provider.complete("hello", system="be terse"))
        self.assertEqual(out, "bedrock says hi")
        # Bedrock's camelCase token counts are recorded.
        self.assertEqual(provider.session_prompt_tokens, 20)
        self.assertEqual(provider.session_completion_tokens, 8)
        # Messages are wrapped in the Converse content shape; system is separate.
        kwargs = provider._client.last_kwargs
        self.assertEqual(kwargs["messages"][0]["content"], [{"text": "hello"}])
        self.assertEqual(kwargs["system"], [{"text": "be terse"}])


if __name__ == "__main__":
    unittest.main()
