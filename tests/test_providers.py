"""Tests for the Mistral and Bedrock provider adapters + create_provider wiring."""

import asyncio
import unittest

from decode.kernel.provider import (
    BedrockProvider,
    MistralProvider,
    create_provider,
)
from decode.models import default_model_registry


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
