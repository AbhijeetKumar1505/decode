import asyncio
import os
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from ..config import Config


class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, prompt: str, system: Optional[str] = None) -> str:
        pass

    @abstractmethod
    async def chat(self, messages: List[Dict[str, str]]) -> str:
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass


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

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        from openai import OpenAI

        self._api_key = api_key or Config.OPENROUTER_API_KEY
        self._model = model or Config.MODEL
        default_headers = {
            "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "https://github.com/decode"),
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

    async def complete(self, prompt: str, system: Optional[str] = None) -> str:
        if not self._client:
            return "[OpenRouter not configured - set OPENROUTER_API_KEY]"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return await self._chat(messages)

    async def chat(self, messages: List[Dict[str, str]]) -> str:
        if not self._client:
            return "[OpenRouter not configured - set OPENROUTER_API_KEY]"
        return await self._chat(messages)

    async def _chat(self, messages: List[Dict[str, str]]) -> str:
        # Free OpenRouter variants share a rate-limited upstream pool, so a
        # transient 429 (or 5xx) is expected under load. Retry with the server's
        # Retry-After hint before giving up, so a momentary limit does not abort
        # the whole agent loop.
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self._client.chat.completions.create(
                    model=self._model, messages=messages, temperature=0.1
                )
                return response.choices[0].message.content
            except Exception as exc:  # narrowed to retryable statuses below
                status = getattr(exc, "status_code", None)
                if status not in self.RETRYABLE_STATUS or attempt == self.MAX_RETRIES - 1:
                    raise
                await asyncio.sleep(self._retry_delay(exc, attempt))
        # Unreachable: the loop either returns or re-raises on the final attempt.
        raise RuntimeError("OpenRouter retry loop exited unexpectedly")

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
        return float(min(2 ** attempt, 8))


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        from openai import OpenAI

        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._model = model or os.getenv("OPENAI_MODEL", "gpt-4o")
        self._client = OpenAI(api_key=self._api_key) if self._api_key else None

    @property
    def name(self) -> str:
        return f"openai/{self._model}"

    async def complete(self, prompt: str, system: Optional[str] = None) -> str:
        if not self._client:
            return "[OpenAI not configured - set OPENAI_API_KEY]"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return await self._chat(messages)

    async def chat(self, messages: List[Dict[str, str]]) -> str:
        return await self._chat(messages)

    async def _chat(self, messages: List[Dict[str, str]]) -> str:
        response = self._client.chat.completions.create(
            model=self._model, messages=messages, temperature=0.1
        )
        return response.choices[0].message.content


class AnthropicProvider(LLMProvider):
    def __init__(
        self, api_key: Optional[str] = None, model: Optional[str] = None
    ):
        from anthropic import Anthropic

        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self._model = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        self._client = Anthropic(api_key=self._api_key) if self._api_key else None

    @property
    def name(self) -> str:
        return f"anthropic/{self._model}"

    async def complete(self, prompt: str, system: Optional[str] = None) -> str:
        if not self._client:
            return "[Anthropic not configured - set ANTHROPIC_API_KEY]"
        response = self._client.messages.create(
            model=self._model,
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096,
            temperature=0.1,
        )
        return response.content[0].text

    async def chat(self, messages: List[Dict[str, str]]) -> str:
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
        return response.content[0].text


def create_provider(provider_name: str = "openrouter", **kwargs) -> LLMProvider:
    providers = {
        "openrouter": OpenRouterProvider,
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
    }
    cls = providers.get(provider_name.lower())
    if not cls:
        raise ValueError(
            f"Unknown provider: {provider_name}. Available: {list(providers.keys())}"
        )
    return cls(**kwargs)
