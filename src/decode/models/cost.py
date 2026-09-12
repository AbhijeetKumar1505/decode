"""Token → cost estimation from model pricing metadata.

Pure and side-effect-free: it turns token counts plus a model's ``ModelCost``
(published per-million-token rates in the registry) into an estimated USD cost.
Free models and unknown ids estimate to ``0.0`` rather than raising, so metering
never breaks a run.
"""

from __future__ import annotations

from .registry import ModelCost, ModelRegistry, ModelSpec

_MILLION = 1_000_000


def estimate_cost(cost: ModelCost, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimated USD cost for one usage split, given a model's pricing."""
    dollars = (prompt_tokens / _MILLION) * cost.input_per_mtok + (
        completion_tokens / _MILLION
    ) * cost.output_per_mtok
    return round(dollars, 6)


def find_model_spec(registry: ModelRegistry, model_id: str) -> ModelSpec | None:
    """Best-effort spec lookup: exact id, else provider-native name match.

    Registry ids are provider-prefixed (``openrouter/z-ai/glm-5.2:free``), while a
    configured ``DECODE_MODEL`` is often the bare slug (``z-ai/glm-5.2:free``), so
    fall back to matching on ``model_name`` or an id suffix.
    """
    if not model_id:
        return None
    spec = registry.get(model_id)
    if spec is not None:
        return spec
    for candidate in registry.all():
        if candidate.model_name == model_id or candidate.id.endswith(f"/{model_id}"):
            return candidate
    return None


def estimate_cost_for(
    registry: ModelRegistry,
    model_id: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """Estimate cost for ``model_id`` using the registry's pricing; 0.0 if unknown."""
    spec = find_model_spec(registry, model_id)
    if spec is None:
        return 0.0
    return estimate_cost(spec.cost, prompt_tokens, completion_tokens)
