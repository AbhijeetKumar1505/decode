# Model Routing

## Status

Decode provides a common `LLMProvider` interface and adapters for OpenRouter (the default orchestrator), OpenAI, and Anthropic. A versioned `ModelRegistry` and a policy-aware `ModelRouter` (`decode/models/`) implement hard data/locality filtering, quality/latency/cost ranking, declarative versioned rules, reproducible pinning, and safe same-locality fallback, and record a concise public reason for each decision. `UniversalAgent.select_model()` exposes this with availability gated by configured credentials. The default chat path remains configuration-driven for the active provider; local model runtimes and additional hosted providers below remain planned.

## Provider interface

Current providers implement:

```python
async def complete(prompt: str, system: str | None = None) -> str: ...
async def chat(messages: list[dict[str, str]]) -> str: ...
@property
def name() -> str: ...
```

The target interface additionally exposes:

- Model capabilities and context limits.
- Structured-output and tool-use support.
- Data locality and retention policy.
- Health, rate-limit, latency, and cost signals.
- Cancellation and streaming.
- Provider request IDs and usage.

## Model registry

Each model entry declares:

| Field | Meaning |
|---|---|
| `id` | Stable provider/model identifier |
| `capabilities` | Chat, structured output, tools, vision, embeddings, long context |
| `data_policy` | Allowed classifications, regions, and retention |
| `context_limit` | Effective input/output limits |
| `cost` | Versioned input/output pricing or local resource estimate |
| `latency_class` | Observed service tier |
| `quality_scores` | Benchmark results by task class |
| `rate_limit` | Provider-published throughput: `tokens_per_minute` and `requests_per_second` (either may be unset) |
| `availability` | Health and rate-limit state |
| `fallback_group` | Compatible alternatives |

### Registered models

The default registry keeps two direct-API hosted models for provider
flexibility (`openai/gpt-4o`, `anthropic/claude-sonnet-4-20250514`) and ships a
catalog of **OpenRouter** models, all served through a single
`OPENROUTER_API_KEY`. Each id has the form `openrouter/<vendor>/<model>:free`, so
the part after the first `/` is the exact OpenRouter slug passed to the API.
Free variants have zero listed cost and share a rate-limited upstream pool.

Chat/planning-capable OpenRouter models (routable) include:

| Model id | Notes |
|---|---|
| `openrouter/z-ai/glm-5.2:free` | Default orchestrator; strongest general model |
| `openrouter/nvidia/nemotron-3-ultra:free` | High-quality general chat |
| `openrouter/minimax/minimax-m3:free` | General chat |
| `openrouter/minimax/minimax-m2.7:free` | General chat |
| `openrouter/google/gemma-4-31b:free` · `openrouter/google/gemma-4-26b-a4b:free` | General chat |
| `openrouter/nvidia/nemotron-3-super:free` · `openrouter/nvidia/nemotron-3.5-lightning:free` | Chat (lightning is fast-latency) |
| `openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning-20260428:free` | Reasoning + vision + audio |
| `openrouter/cohere/north-mini-code-20260617:free` · `openrouter/poolside/laguna-s-2.1:free` · `openrouter/poolside/laguna-xs-2.1:free` | Code |
| `openrouter/thinkingmachines/inkling:free` · `openrouter/thinkingmachines/inkling-small:free` | Chat |
| `openrouter/dots/dots-3-note-preview-20260813:free` · `openrouter/inclusionai/ling-3.0-flash-fin-20260827:free` · `openrouter/liquid/lfm-2.5-2.6b-20260811:free` | Chat |

Non-chat OpenRouter models are also registered but carry no `chat` capability,
so the router never selects them for a chat/planning task: embeddings
(`liquid/lfm-2.5-embedding-350m-20260818`, `nvidia/nemotron-3-embed-1b-20260716`,
`nvidia/llama-nemotron-embed-vl-1b-v2-20260224`), rerank
(`nvidia/llama-nemotron-rerank-vl-1b-v2`), audio/TTS
(`deepgram/flux-tts-20260812`, `fish-audio/s2.1-pro-free-20260729`), and content
safety (`nvidia/nemotron-3.5-content-safety-20260604`).

Switch the active model at runtime with `/model <id>` (bare name or
`provider/name`); `/model` with no argument lists the registry. The active model
name is passed straight to the provider, so any model the key serves works.
Free `:free` variants can return HTTP 429 under load; the OpenRouter adapter
retries with the server's `Retry-After` hint, and adding your own provider key on
OpenRouter grants dedicated limits.

## Routing inputs

- Task class and required model capabilities.
- Data classification and provider policy.
- User/provider allowlist.
- Local-only or offline requirement.
- Context and output size.
- Quality threshold.
- Latency deadline.
- Cost budget.
- Provider health and rate limits.
- Reproducibility pinning.

Safety and data policy are hard filters. Cost and latency are optimization signals.

## Routing process

```text
Task requirements
      |
Policy and data filter
      |
Capability filter
      |
Health and limit filter
      |
Quality / latency / cost ranking
      |
Selected model + recorded reason
```

## Fallback strategy

Fallback occurs only when:

- The task allows fallback.
- The alternative satisfies the same data and capability policy.
- The request can be safely retried.
- The model change is recorded.

Do not fallback across a local-only boundary, send sensitive context to a less-trusted provider, or repeat a consequential tool action. A fallback re-runs model inference only.

## Cost optimization

- Use smaller evaluated models for classification and extraction.
- Reserve stronger models for planning or ambiguous analysis.
- Reuse safe deterministic transformations without resending secrets.
- Set per-project and per-task budgets.
- Record actual usage and pricing version.

Cost never overrides quality or safety thresholds.

## Latency optimization

- Route interactive tasks to models meeting the deadline.
- Stream responses where supported.
- Parallelize independent read-only model analyses within budget.
- Prefer local models when network latency or privacy dominates.
- Degrade explicitly rather than silently truncating required context.

## Routing rules

Rules are declarative and versioned:

```yaml
- name: confidential-local
  when:
    data_classification: confidential
  require:
    locality: local
- name: structured-plan
  when:
    task_class: planning
  require:
    capabilities: [structured_output]
  optimize: [quality, latency]
```

Every decision records the matching rule and selected model.

## Providers

| Provider/runtime | Status | Notes |
|---|---|---|
| OpenRouter | Implemented | Default orchestrator; OpenAI-compatible gateway, one key for all `openrouter/*` models, retries transient 429/5xx |
| OpenAI | Implemented | Optional API key and model |
| Anthropic | Implemented | Optional API key and model |
| Gemini | Planned | Requires adapter and evaluation |
| Groq | Planned | Hosted inference routing candidate |
| Together AI | Planned | Hosted open-model provider candidate |
| Azure OpenAI | Planned | Enterprise identity/region adapter |
| Ollama | Planned | Local model runtime |
| vLLM | Planned | Local/team model server |
| llama.cpp | Planned | Resource-conscious local runtime |

## Custom providers

A custom adapter must implement the provider contract, declare data handling and capabilities, expose health, redact logs, propagate cancellation, and pass conformance tests. Provider plugins cannot receive unrestricted memory by default.

## Prompt and response safety

- Separate trusted system policy from untrusted task content.
- Label retrieved artifacts as data, not instructions.
- Validate structured output.
- Apply output limits.
- Never treat model output as authorization.
- Record provider/model identity without logging secrets.

## Evaluation

Route changes require task-specific benchmarks for correctness, evidence citation, refusal behavior, structured-output validity, latency, cost, and prompt-injection resistance.
