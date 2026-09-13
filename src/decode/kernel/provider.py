import asyncio
import os
from abc import ABC, abstractmethod
from typing import Any

from ..config import Config


class LLMProvider(ABC):
    # Class-level defaults so token accounting is always readable, even on
    # instances built via ``__new__`` (e.g. in tests) that skip ``__init__``.
    last_prompt_tokens: int = 0
    last_completion_tokens: int = 0
    session_tokens: int = 0
    # Cumulative split, so per-session cost can be estimated (input and output
    # tokens are priced differently).
    session_prompt_tokens: int = 0
    session_completion_tokens: int = 0

    def __init__(self) -> None:
        # Token accounting surfaced to the TUI (top bar + streaming meter).
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        self.session_tokens = 0
        self.session_prompt_tokens = 0
        self.session_completion_tokens = 0

    @abstractmethod
    async def complete(self, prompt: str, system: str | None = None) -> str:
        pass

    @abstractmethod
    async def chat(self, messages: list[dict[str, Any]]) -> str:
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    def assistant_message(self, content: str) -> dict[str, Any]:
        """Build the assistant history entry for a completed model response."""
        return {"role": "assistant", "content": content}

    def _record_usage(self, usage) -> None:
        """Accumulate token usage from a provider response's ``usage`` object.

        Handles both the OpenAI/OpenRouter shape (``prompt_tokens`` /
        ``completion_tokens``) and the Anthropic shape (``input_tokens`` /
        ``output_tokens``). Missing usage is a no-op.
        """
        if not usage:
            return
        prompt = getattr(usage, "prompt_tokens", None)
        if prompt is None:
            prompt = getattr(usage, "input_tokens", 0)
        completion = getattr(usage, "completion_tokens", None)
        if completion is None:
            completion = getattr(usage, "output_tokens", 0)
        try:
            self._record_usage_counts(int(prompt or 0), int(completion or 0))
        except (TypeError, ValueError):
            return  # non-numeric usage (e.g. a bare mock) — ignore rather than crash

    def _record_usage_counts(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Accumulate explicit token counts (e.g. Bedrock's ``inputTokens``)."""
        self.last_prompt_tokens = int(prompt_tokens or 0)
        self.last_completion_tokens = int(completion_tokens or 0)
        self.session_tokens += self.last_prompt_tokens + self.last_completion_tokens
        self.session_prompt_tokens += self.last_prompt_tokens
        self.session_completion_tokens += self.last_completion_tokens


class OpenRouterProvider(LLMProvider):
    """OpenRouter orchestrator — an OpenAI-compatible gateway to many models.

    OpenRouter exposes an OpenAI-compatible API, so we reuse the OpenAI SDK
    pointed at the OpenRouter base URL. A single ``OPENROUTER_API_KEY`` unlocks
    every model registered in the router. The optional ``HTTP-Referer`` and
    ``X-Title`` headers are OpenRouter's leaderboard attribution fields.
    """

    BASE_URL = "https://openrouter.ai/api/v1"
    #: HTTP statuses worth retrying (transient upstream/shared-pool failures).
    RETRYABLE_STATUS = {429, 500, 502, 503, 529}
    MAX_RETRIES = 4

    def __init__(self, api_key: str | None = None, model: str | None = None):
        super().__init__()
        from openai import OpenAI

        self._api_key = api_key or Config.OPENROUTER_API_KEY
        self._model = model or Config.MODEL
        self._last_assistant_message: dict[str, Any] | None = None
        default_headers = {
            "HTTP-Referer": os.getenv(
                "OPENROUTER_SITE_URL", "https://github.com/decode"
            ),
            "X-Title": os.getenv("OPENROUTER_APP_NAME", "Decode"),
        }
        self._client = (
            OpenAI(
                api_key=self._api_key,
                base_url=self.BASE_URL,
                default_headers=default_headers,
            )
            if self._api_key
            else None
        )

    @property
    def name(self) -> str:
        return f"openrouter/{self._model}"

    async def complete(self, prompt: str, system: str | None = None) -> str:
        if not self._client:
            return "[OpenRouter not configured - set OPENROUTER_API_KEY]"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return await self._chat(messages)

    async def chat(self, messages: list[dict[str, Any]]) -> str:
        if not self._client:
            return "[OpenRouter not configured - set OPENROUTER_API_KEY]"
        return await self._chat(messages)

    async def _chat(self, messages: list[dict[str, Any]]) -> str:
        # Free OpenRouter variants share a rate-limited upstream pool, so a
        # transient 429 (or 5xx) is expected under load. Retry with the server's
        # Retry-After hint before giving up, so a momentary limit does not abort
        # the whole agent loop.
        self._last_assistant_message = None
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    temperature=0.1,
                    extra_body={"reasoning": {"enabled": True}},
                )
                self._record_usage(getattr(response, "usage", None))
                message = response.choices[0].message
                content = message.content or ""
                history: dict[str, Any] = {
                    "role": "assistant",
                    "content": content,
                }
                reasoning_details = getattr(message, "reasoning_details", None)
                if reasoning_details is None:
                    model_extra = getattr(message, "model_extra", None)
                    if isinstance(model_extra, dict):
                        reasoning_details = model_extra.get("reasoning_details")
                if reasoning_details is not None:
                    history["reasoning_details"] = reasoning_details
                self._last_assistant_message = history
                return content
            except Exception as exc:  # narrowed to retryable statuses below
                status = getattr(exc, "status_code", None)
                if (
                    status not in self.RETRYABLE_STATUS
                    or attempt == self.MAX_RETRIES - 1
                ):
                    raise
                await asyncio.sleep(self._retry_delay(exc, attempt))
        # Unreachable: the loop either returns or re-raises on the final attempt.
        raise RuntimeError("OpenRouter retry loop exited unexpectedly")

    def assistant_message(self, content: str) -> dict[str, Any]:
        history = getattr(self, "_last_assistant_message", None)
        if history is not None and history.get("content") == content:
            return dict(history)
        return super().assistant_message(content)

    @staticmethod
    def _retry_delay(exc: Exception, attempt: int) -> float:
        """Honor the server's ``Retry-After`` header; fall back to backoff."""
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        if headers:
            raw = headers.get("Retry-After") or headers.get("retry-after")
            if raw:
                try:
                    return max(0.0, float(raw))
                except (TypeError, ValueError):
                    pass
        return float(min(2**attempt, 8))


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str | None = None, model: str | None = None):
        super().__init__()
        from openai import OpenAI

        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._model = model or os.getenv("OPENAI_MODEL", "gpt-4o")
        self._client = OpenAI(api_key=self._api_key) if self._api_key else None

    @property
    def name(self) -> str:
        return f"openai/{self._model}"

    async def complete(self, prompt: str, system: str | None = None) -> str:
        if not self._client:
            return "[OpenAI not configured - set OPENAI_API_KEY]"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return await self._chat(messages)

    async def chat(self, messages: list[dict[str, Any]]) -> str:
        return await self._chat(messages)

    async def _chat(self, messages: list[dict[str, Any]]) -> str:
        response = self._client.chat.completions.create(
            model=self._model, messages=messages, temperature=0.1
        )
        self._record_usage(getattr(response, "usage", None))
        return response.choices[0].message.content


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str | None = None, model: str | None = None):
        super().__init__()
        from anthropic import Anthropic

        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self._model = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        self._client = Anthropic(api_key=self._api_key) if self._api_key else None

    @property
    def name(self) -> str:
        return f"anthropic/{self._model}"

    async def complete(self, prompt: str, system: str | None = None) -> str:
        if not self._client:
            return "[Anthropic not configured - set ANTHROPIC_API_KEY]"
        response = self._client.messages.create(
            model=self._model,
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096,
            temperature=0.1,
        )
        self._record_usage(getattr(response, "usage", None))
        return response.content[0].text

    async def chat(self, messages: list[dict[str, Any]]) -> str:
        if not self._client:
            return "[Anthropic not configured - set ANTHROPIC_API_KEY]"
        # Anthropic requires system prompts as a top-level param, not inline messages.
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        convo = [m for m in messages if m.get("role") != "system"]
        response = self._client.messages.create(
            model=self._model,
            system="\n\n".join(system_parts),
            messages=convo,
            max_tokens=4096,
            temperature=0.1,
        )
        self._record_usage(getattr(response, "usage", None))
        return response.content[0].text


class MistralProvider(LLMProvider):
    """Mistral AI via the official ``mistralai`` SDK (OpenAI-shaped usage)."""

    _UNCONFIGURED = (
        "[Mistral not configured - install mistralai and set MISTRAL_API_KEY]"
    )

    def __init__(self, api_key: str | None = None, model: str | None = None):
        super().__init__()
        self._api_key = api_key or os.getenv("MISTRAL_API_KEY")
        self._model = model or os.getenv("MISTRAL_MODEL", "mistral-large-latest")
        self._client = None
        if self._api_key:
            try:
                from mistralai import Mistral

                self._client = Mistral(api_key=self._api_key)
            except Exception:
                self._client = None  # SDK missing or client init failed

    @property
    def name(self) -> str:
        return f"mistral/{self._model}"

    async def complete(self, prompt: str, system: str | None = None) -> str:
        if not self._client:
            return self._UNCONFIGURED
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return await self._chat(messages)

    async def chat(self, messages: list[dict[str, Any]]) -> str:
        if not self._client:
            return self._UNCONFIGURED
        return await self._chat(messages)

    async def _chat(self, messages: list[dict[str, Any]]) -> str:
        response = self._client.chat.complete(
            model=self._model, messages=messages, temperature=0.1
        )
        self._record_usage(getattr(response, "usage", None))
        return response.choices[0].message.content


class BedrockProvider(LLMProvider):
    """AWS Bedrock via boto3's ``bedrock-runtime`` Converse API.

    Auth is standard AWS credentials (env vars, shared config, or an instance
    role) plus a region — there is no single API key. boto3 is an optional extra
    (``pip install 'decode[bedrock]'``); without it, or without credentials, the
    provider stays unconfigured and returns a clear message rather than crashing.
    """

    def __init__(
        self,
        api_key: str | None = None,  # unused; AWS uses its own credential chain
        model: str | None = None,
        region: str | None = None,
    ):
        super().__init__()
        self._model = model or os.getenv(
            "BEDROCK_MODEL", "anthropic.claude-3-5-sonnet-20240620-v1:0"
        )
        self._region = (
            region
            or os.getenv("AWS_REGION")
            or os.getenv("AWS_DEFAULT_REGION")
            or "us-east-1"
        )
        try:
            import boto3

            self._client = boto3.client("bedrock-runtime", region_name=self._region)
        except Exception:
            self._client = None  # boto3 missing or client init failed

    @property
    def name(self) -> str:
        return f"bedrock/{self._model}"

    async def complete(self, prompt: str, system: str | None = None) -> str:
        return await self._converse([{"role": "user", "content": prompt}], system)

    async def chat(self, messages: list[dict[str, Any]]) -> str:
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        convo = [m for m in messages if m.get("role") != "system"]
        return await self._converse(convo, "\n\n".join(system_parts) or None)

    async def _converse(self, convo: list[dict[str, Any]], system: str | None) -> str:
        if self._client is None:
            return (
                "[Bedrock not configured - install boto3 and set AWS credentials "
                "and region]"
            )
        messages = [
            {"role": m["role"], "content": [{"text": str(m.get("content", ""))}]}
            for m in convo
        ]
        kwargs: dict = {
            "modelId": self._model,
            "messages": messages,
            "inferenceConfig": {"maxTokens": 4096, "temperature": 0.1},
        }
        if system:
            kwargs["system"] = [{"text": system}]
        response = self._client.converse(**kwargs)
        usage = response.get("usage", {}) or {}
        self._record_usage_counts(
            usage.get("inputTokens", 0), usage.get("outputTokens", 0)
        )
        return response["output"]["message"]["content"][0]["text"]


def create_provider(provider_name: str = "openrouter", **kwargs) -> LLMProvider:
    providers = {
        "openrouter": OpenRouterProvider,
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "mistral": MistralProvider,
        "bedrock": BedrockProvider,
    }
    cls = providers.get(provider_name.lower())
    if not cls:
        raise ValueError(
            f"Unknown provider: {provider_name}. Available: {list(providers.keys())}"
        )
    return cls(**kwargs)
