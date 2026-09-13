"""Versioned model registry.

Each entry declares what a model can do, the data policy it satisfies, its
context limit, cost, latency class, task-quality scores, availability, and its
fallback group. The registry is descriptive metadata only — it never holds
credentials and never performs inference.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

MODEL_SCHEMA_VERSION = 1

# public < internal < confidential < restricted
_CLASSIFICATION_ORDER = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "restricted": 3,
}


def classification_rank(value: str) -> int:
    if value not in _CLASSIFICATION_ORDER:
        raise ValueError(f"unknown data classification '{value}'")
    return _CLASSIFICATION_ORDER[value]


class DataPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Highest data classification the model is permitted to receive.
    max_classification: str = "internal"
    #: "local" for on-device runtimes, "hosted" for remote APIs.
    locality: str = "hosted"
    retention: str = "provider-default"

    def accepts(self, classification: str) -> bool:
        return classification_rank(classification) <= classification_rank(
            self.max_classification
        )


class ModelCost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_per_mtok: float = 0.0
    output_per_mtok: float = 0.0
    pricing_version: str = ""


class RateLimit(BaseModel):
    """Provider-published throughput limits for a model (descriptive metadata)."""

    model_config = ConfigDict(extra="forbid")

    #: Tokens-per-minute cap; ``None`` when the provider does not publish one.
    tokens_per_minute: int | None = Field(default=None, ge=1)
    #: Requests-per-second cap.
    requests_per_second: float | None = Field(default=None, gt=0)


class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=256)
    provider: str = Field(min_length=1, max_length=64)
    version: int = Field(default=MODEL_SCHEMA_VERSION, ge=1)
    capabilities: list[str] = Field(default_factory=list)
    data_policy: DataPolicy = Field(default_factory=DataPolicy)
    context_limit: int = Field(default=8_192, ge=1)
    cost: ModelCost = Field(default_factory=ModelCost)
    rate_limit: RateLimit = Field(default_factory=RateLimit)
    latency_class: str = "standard"
    quality_scores: dict[str, float] = Field(default_factory=dict)
    available: bool = True
    rate_limited: bool = False
    fallback_group: str = ""

    @property
    def model_name(self) -> str:
        """The provider-native model name (the id without the ``provider/`` prefix)."""
        return self.id.split("/", 1)[1] if "/" in self.id else self.id

    def has_capabilities(self, required: list[str]) -> bool:
        return set(required) <= set(self.capabilities)

    def quality_for(self, task_class: str) -> float:
        return self.quality_scores.get(task_class, 0.0)


class ModelRegistry:
    """A validated, in-memory set of model specs keyed by id."""

    def __init__(self, models: list[ModelSpec] | None = None) -> None:
        self._models: dict[str, ModelSpec] = {}
        for spec in models or []:
            self.register(spec)

    def register(self, spec: ModelSpec) -> None:
        if spec.id in self._models:
            raise ValueError(f"duplicate model id '{spec.id}'")
        self._models[spec.id] = spec

    def get(self, model_id: str) -> ModelSpec | None:
        return self._models.get(model_id)

    def all(self) -> list[ModelSpec]:
        return list(self._models.values())

    def in_group(self, fallback_group: str) -> list[ModelSpec]:
        return [
            spec
            for spec in self._models.values()
            if fallback_group and spec.fallback_group == fallback_group
        ]


class OpenRouterCatalogError(RuntimeError):
    """The live OpenRouter catalogue could not be fetched or validated."""


class OpenRouterArchitecture(BaseModel):
    model_config = ConfigDict(extra="ignore")

    input_modalities: list[str] = Field(default_factory=list)
    output_modalities: list[str] = Field(default_factory=list)


class OpenRouterPricing(BaseModel):
    model_config = ConfigDict(extra="ignore")

    prompt: str | float = "0"
    completion: str | float = "0"


class OpenRouterCatalogModel(BaseModel):
    """Fields consumed from one model returned by OpenRouter's Models API."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=240)
    context_length: int | None = Field(default=None, ge=0)
    architecture: OpenRouterArchitecture = Field(default_factory=OpenRouterArchitecture)
    pricing: OpenRouterPricing = Field(default_factory=OpenRouterPricing)
    supported_parameters: list[str] = Field(default_factory=list)


class OpenRouterCatalogResult(BaseModel):
    """Validated live catalogue plus its partial-parse status."""

    model_config = ConfigDict(extra="forbid")

    models: list[ModelSpec]
    total_count: int
    skipped: int = 0


def _per_million(value: str | float) -> float:
    try:
        per_token = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("invalid model pricing") from None
    if per_token == -1:
        return 0.0
    if not math.isfinite(per_token) or per_token < 0:
        raise ValueError("invalid model pricing")
    return per_token * 1_000_000


def _pricing_unavailable(pricing: OpenRouterPricing) -> bool:
    try:
        return float(pricing.prompt) == -1 or float(pricing.completion) == -1
    except (TypeError, ValueError, OverflowError):
        return False


def _catalog_capabilities(model: OpenRouterCatalogModel) -> list[str]:
    inputs = set(model.architecture.input_modalities)
    outputs = set(model.architecture.output_modalities)
    parameters = set(model.supported_parameters)
    capabilities: set[str] = set()
    if "text" in outputs:
        capabilities.add("chat")
    if "image" in inputs:
        capabilities.add("vision")
    if "image" in outputs:
        capabilities.add("image_generation")
    if "audio" in inputs or "audio" in outputs:
        capabilities.add("audio")
    if "file" in inputs:
        capabilities.add("file")
    if "embeddings" in outputs:
        capabilities.add("embeddings")
    if "tools" in parameters:
        capabilities.add("tools")
    if {"structured_outputs", "response_format"} & parameters:
        capabilities.add("structured_output")
    if {"reasoning", "include_reasoning"} & parameters:
        capabilities.add("reasoning")
    if (model.context_length or 0) >= 32_768:
        capabilities.add("long_context")
    return sorted(capabilities)


def _catalog_fallback_group(capabilities: list[str]) -> str:
    for capability in ("embeddings", "image_generation", "audio"):
        if capability in capabilities:
            return f"openrouter-{capability}"
    return "openrouter-general"


def _catalog_model_spec(
    model: OpenRouterCatalogModel,
    curated: ModelSpec | None = None,
) -> ModelSpec:
    capabilities = _catalog_capabilities(model)
    if curated is not None and "code" in curated.capabilities:
        capabilities = sorted({*capabilities, "code"})
    return ModelSpec(
        id=f"openrouter/{model.id}",
        provider="openrouter",
        capabilities=capabilities,
        data_policy=DataPolicy(max_classification="internal", locality="hosted"),
        context_limit=model.context_length or 8_192,
        cost=ModelCost(
            input_per_mtok=_per_million(model.pricing.prompt),
            output_per_mtok=_per_million(model.pricing.completion),
            pricing_version=(
                "openrouter-live-unavailable"
                if _pricing_unavailable(model.pricing)
                else "openrouter-live"
            ),
        ),
        rate_limit=curated.rate_limit if curated is not None else RateLimit(),
        latency_class=curated.latency_class if curated is not None else "standard",
        quality_scores=curated.quality_scores if curated is not None else {},
        fallback_group=(
            curated.fallback_group
            if curated is not None
            else _catalog_fallback_group(capabilities)
        ),
    )


def fetch_openrouter_catalog(
    api_key: str = "",
    *,
    timeout: float = 10.0,
    http_get: Callable[..., Any] | None = None,
) -> OpenRouterCatalogResult:
    """Fetch every modality from OpenRouter's public model catalogue.

    The endpoint is fixed to prevent a caller from turning catalogue refresh into
    an arbitrary network request. Invalid individual records are counted and
    skipped; a missing/empty catalogue fails rather than replacing the registry.
    """
    if isinstance(timeout, bool) or not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise ValueError("catalog timeout must be between 0 and 60 seconds")
    if http_get is None:
        import requests

        http_get = requests.get
    headers = {"Accept": "application/json", "User-Agent": "Decode"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        response = http_get(
            "https://openrouter.ai/api/v1/models",
            params={"output_modalities": "all"},
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise OpenRouterCatalogError(
            f"OpenRouter catalogue request failed ({type(exc).__name__})"
        ) from None
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise OpenRouterCatalogError(
            "OpenRouter catalogue returned an invalid response"
        )

    curated_registry = default_model_registry()
    curated = {
        spec.model_name: spec
        for spec in curated_registry.all()
        if spec.provider == "openrouter"
    }
    models: dict[str, ModelSpec] = {}
    skipped = 0
    for raw in payload["data"]:
        try:
            entry = OpenRouterCatalogModel.model_validate(raw)
            spec = _catalog_model_spec(entry, curated.get(entry.id))
            if spec.id in models:
                raise ValueError("duplicate model id")
        except (TypeError, ValueError):
            skipped += 1
            continue
        models[spec.id] = spec
    if not models:
        raise OpenRouterCatalogError("OpenRouter catalogue contained no valid models")
    return OpenRouterCatalogResult(
        models=sorted(models.values(), key=lambda spec: spec.id),
        total_count=len(payload["data"]),
        skipped=skipped,
    )


def registry_with_openrouter_catalog(
    result: OpenRouterCatalogResult,
    base: ModelRegistry | None = None,
) -> ModelRegistry:
    """Replace the static OpenRouter fallback set with a live catalogue."""
    base = base or default_model_registry()
    direct_models = [spec for spec in base.all() if spec.provider != "openrouter"]
    return ModelRegistry([*direct_models, *result.models])


def _openrouter(
    slug: str,
    *,
    capabilities: list[str],
    context_limit: int = 128_000,
    latency_class: str = "standard",
    quality_scores: dict[str, float] | None = None,
    fallback_group: str = "openrouter-general",
    rate_limit: RateLimit | None = None,
) -> ModelSpec:
    """Build a free OpenRouter model spec.

    The id is ``openrouter/<vendor>/<model>:free`` so :pyattr:`ModelSpec.model_name`
    (everything after the first ``/``) yields the exact OpenRouter slug we pass to
    the API. Free variants have zero cost.
    """
    return ModelSpec(
        id=f"openrouter/{slug}",
        provider="openrouter",
        capabilities=capabilities,
        data_policy=DataPolicy(max_classification="internal", locality="hosted"),
        context_limit=context_limit,
        cost=ModelCost(pricing_version="openrouter-free"),
        rate_limit=rate_limit or RateLimit(),
        latency_class=latency_class,
        quality_scores=quality_scores or {},
        fallback_group=fallback_group,
    )


def default_model_registry() -> ModelRegistry:
    """Ship metadata for the OpenRouter orchestrator plus the two direct-API
    hosted providers (OpenAI, Anthropic) kept for provider flexibility.

    OpenRouter is the default orchestrator: a single ``OPENROUTER_API_KEY``
    unlocks every ``openrouter/*`` model below. Local runtimes (Ollama, vLLM,
    llama.cpp) are planned, so no local model is registered; `local_only`
    routing therefore fails closed with a clear reason until one is added.
    """
    _CHAT = ["chat", "structured_output", "tools", "long_context"]
    _CODE = ["chat", "structured_output", "tools", "code", "long_context"]

    return ModelRegistry(
        [
            # ── Direct-API hosted providers (used via their own API keys) ──
            ModelSpec(
                id="openai/gpt-4o",
                provider="openai",
                capabilities=[
                    "chat",
                    "structured_output",
                    "tools",
                    "vision",
                    "long_context",
                ],
                data_policy=DataPolicy(
                    max_classification="internal", locality="hosted"
                ),
                context_limit=128_000,
                cost=ModelCost(
                    input_per_mtok=2.5, output_per_mtok=10.0, pricing_version="2025-06"
                ),
                latency_class="standard",
                quality_scores={"planning": 0.9, "extraction": 0.88, "analysis": 0.9},
                fallback_group="hosted-general",
            ),
            ModelSpec(
                id="anthropic/claude-sonnet-4-20250514",
                provider="anthropic",
                capabilities=[
                    "chat",
                    "structured_output",
                    "tools",
                    "vision",
                    "long_context",
                ],
                data_policy=DataPolicy(
                    max_classification="internal", locality="hosted"
                ),
                context_limit=200_000,
                cost=ModelCost(
                    input_per_mtok=3.0, output_per_mtok=15.0, pricing_version="2025-06"
                ),
                latency_class="standard",
                quality_scores={"planning": 0.91, "extraction": 0.88, "analysis": 0.92},
                fallback_group="hosted-general",
            ),
            ModelSpec(
                id="bedrock/anthropic.claude-3-5-sonnet-20240620-v1:0",
                provider="bedrock",
                capabilities=[
                    "chat",
                    "structured_output",
                    "tools",
                    "vision",
                    "long_context",
                ],
                data_policy=DataPolicy(
                    max_classification="internal", locality="hosted"
                ),
                context_limit=200_000,
                cost=ModelCost(
                    input_per_mtok=3.0, output_per_mtok=15.0, pricing_version="2025-06"
                ),
                latency_class="standard",
                quality_scores={"planning": 0.9, "extraction": 0.88, "analysis": 0.9},
                fallback_group="hosted-general",
            ),
            # ── OpenRouter free models (all served via OPENROUTER_API_KEY) ──
            # OpenRouter's free router is the default and selects a free model.
            _openrouter(
                "openrouter/free",
                capabilities=[*_CHAT, "reasoning", "vision"],
                context_limit=200_000,
            ),
            # Z.ai — strongest curated general model in the offline fallback.
            _openrouter(
                "z-ai/glm-5.2:free",
                capabilities=_CHAT,
                quality_scores={"planning": 0.88, "extraction": 0.86, "analysis": 0.88},
            ),
            # Cohere
            _openrouter(
                "cohere/north-mini-code-20260617:free",
                capabilities=_CODE,
                quality_scores={
                    "planning": 0.78,
                    "extraction": 0.78,
                    "analysis": 0.77,
                    "code": 0.86,
                },
            ),
            # Dots Studio
            _openrouter(
                "dots/dots-3-note-preview-20260813:free",
                capabilities=_CHAT,
                quality_scores={"planning": 0.74, "extraction": 0.76, "analysis": 0.75},
            ),
            # Google Gemma 4
            _openrouter(
                "google/gemma-4-26b-a4b:free",
                capabilities=_CHAT,
                quality_scores={"planning": 0.8, "extraction": 0.8, "analysis": 0.8},
            ),
            _openrouter(
                "google/gemma-4-31b:free",
                capabilities=_CHAT,
                quality_scores={"planning": 0.82, "extraction": 0.82, "analysis": 0.82},
            ),
            # inclusionai
            _openrouter(
                "inclusionai/ling-3.0-flash-fin-20260827:free",
                capabilities=_CHAT,
                latency_class="fast",
                quality_scores={"planning": 0.76, "extraction": 0.78, "analysis": 0.77},
            ),
            # Liquid
            _openrouter(
                "liquid/lfm-2.5-2.6b-20260811:free",
                capabilities=["chat", "structured_output", "tools"],
                context_limit=32_000,
                latency_class="fast",
                quality_scores={"planning": 0.68, "extraction": 0.7, "analysis": 0.68},
            ),
            # MiniMax
            _openrouter(
                "minimax/minimax-m2.7:free",
                capabilities=_CHAT,
                quality_scores={"planning": 0.83, "extraction": 0.82, "analysis": 0.83},
            ),
            _openrouter(
                "minimax/minimax-m3:free",
                capabilities=_CHAT,
                quality_scores={"planning": 0.85, "extraction": 0.84, "analysis": 0.85},
            ),
            # Nvidia Nemotron — chat/reasoning
            _openrouter(
                "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning-20260428:free",
                capabilities=[
                    "chat",
                    "structured_output",
                    "tools",
                    "vision",
                    "audio",
                    "reasoning",
                    "long_context",
                ],
                quality_scores={"planning": 0.84, "extraction": 0.82, "analysis": 0.85},
            ),
            _openrouter(
                "nvidia/nemotron-3-super:free",
                capabilities=_CHAT,
                quality_scores={"planning": 0.84, "extraction": 0.83, "analysis": 0.84},
            ),
            _openrouter(
                "nvidia/nemotron-3-ultra:free",
                capabilities=_CHAT,
                quality_scores={"planning": 0.87, "extraction": 0.85, "analysis": 0.87},
            ),
            _openrouter(
                "nvidia/nemotron-3.5-lightning:free",
                capabilities=_CHAT,
                context_limit=32_000,
                latency_class="fast",
                quality_scores={"planning": 0.78, "extraction": 0.79, "analysis": 0.78},
            ),
            # poolside — code
            _openrouter(
                "poolside/laguna-s-2.1:free",
                capabilities=_CODE,
                quality_scores={
                    "planning": 0.79,
                    "extraction": 0.78,
                    "analysis": 0.78,
                    "code": 0.85,
                },
            ),
            _openrouter(
                "poolside/laguna-xs-2.1:free",
                capabilities=_CODE,
                latency_class="fast",
                quality_scores={
                    "planning": 0.74,
                    "extraction": 0.74,
                    "analysis": 0.73,
                    "code": 0.8,
                },
            ),
            # thinkingmachines
            _openrouter(
                "thinkingmachines/inkling:free",
                capabilities=_CHAT,
                quality_scores={"planning": 0.81, "extraction": 0.8, "analysis": 0.81},
            ),
            _openrouter(
                "thinkingmachines/inkling-small:free",
                capabilities=["chat", "structured_output", "tools"],
                context_limit=32_000,
                latency_class="fast",
                quality_scores={"planning": 0.73, "extraction": 0.74, "analysis": 0.73},
            ),
            # ── OpenRouter free non-chat models (embeddings / rerank / audio / safety) ──
            # These carry no chat capability, so the router never selects them for a
            # chat/planning task; they are registered so callers can address them.
            _openrouter(
                "deepgram/flux-tts-20260812:free",
                capabilities=["audio", "tts"],
                context_limit=8_192,
                fallback_group="openrouter-audio",
            ),
            _openrouter(
                "fish-audio/s2.1-pro-free-20260729:free",
                capabilities=["audio", "tts"],
                context_limit=8_192,
                fallback_group="openrouter-audio",
            ),
            _openrouter(
                "liquid/lfm-2.5-embedding-350m-20260818:free",
                capabilities=["embeddings"],
                context_limit=8_192,
                fallback_group="openrouter-embeddings",
            ),
            _openrouter(
                "nvidia/llama-nemotron-embed-vl-1b-v2-20260224:free",
                capabilities=["embeddings", "vision"],
                context_limit=8_192,
                fallback_group="openrouter-embeddings",
            ),
            _openrouter(
                "nvidia/nemotron-3-embed-1b-20260716:free",
                capabilities=["embeddings"],
                context_limit=8_192,
                fallback_group="openrouter-embeddings",
            ),
            _openrouter(
                "nvidia/llama-nemotron-rerank-vl-1b-v2:free",
                capabilities=["rerank", "vision"],
                context_limit=8_192,
                fallback_group="openrouter-rerank",
            ),
            _openrouter(
                "nvidia/nemotron-3.5-content-safety-20260604:free",
                capabilities=["classification", "moderation"],
                context_limit=8_192,
                fallback_group="openrouter-safety",
            ),
        ]
    )
