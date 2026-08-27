# Configuration

## Principles

- Safe local defaults.
- Explicit environment and project overrides.
- Secrets separated from ordinary configuration.
- Typed validation at startup.
- Observable effective configuration with secrets redacted.
- Unknown critical settings fail fast.

## Precedence

Target precedence, highest first:

1. Explicit CLI flag.
2. Project configuration.
3. Environment variable or `.env`.
4. User configuration.
5. Built-in default.

Security policy may impose a non-overridable ceiling.

## Current environment variables

| Variable | Purpose | Default |
|---|---|---|
| `DECODE_PROVIDER` | Selected provider: `openrouter`, `openai`, or `anthropic` | `openrouter` |
| `OPENROUTER_API_KEY` | OpenRouter provider credential (unlocks every `openrouter/*` model) | None |
| `DECODE_MODEL` | Active model slug (OpenRouter slug when the provider is `openrouter`) | `z-ai/glm-5.2:free` |
| `OPENROUTER_EMBED_MODEL` | Model used for semantic-memory embeddings | `nvidia/nemotron-3-embed-1b-20260716:free` |
| `DECODE_EXECUTOR` | Default execution provider | `local` |
| `MAX_ITERATIONS` | Agent iteration limit | `20` |
| `MEMORY_PATH` | Semantic-memory files | `./data/models/` |
| `LOGS_PATH` | Structured logs | `./logs/` |
| `AUDIT_PATH` | Audit JSONL files | `./audit/` |
| `FEEDBACK_PATH` | Execution feedback | `./feedback/` |
| `DECODE_PLAYBOOKS_DIR` | Extra markdown-playbook directories (`os.pathsep`-separated) | None |
| `OPENAI_API_KEY` | OpenAI credential | None |
| `OPENAI_MODEL` | OpenAI model | `gpt-4o` |
| `ANTHROPIC_API_KEY` | Anthropic credential | None |
| `ANTHROPIC_MODEL` | Anthropic model | Provider adapter default |
| `MONGODB_URI` | MongoDB connection string; when set, selects the MongoDB operational backend instead of local SQLite | None |
| `MONGODB_PASSWORD` | Password substituted for a `<db_password>` placeholder in `MONGODB_URI` (URL-encoded automatically) | None |
| `MONGODB_DB` | MongoDB database name | `decode` |
| `DECODE_SEARCH_ENGINE` | Persistent web search engine for the agent | `duckduckgo` |

`.env.example` is the source template. The real `.env` is local and must not be committed.

### Operational store backend

The operational store defaults to local SQLite (`data/decode.db`). Setting `MONGODB_URI` selects a MongoDB backend (`MongoSessionStore`) with the same store contract; `create_store()` resolves the backend at startup. A configured-but-unreachable MongoDB fails loudly rather than silently downgrading. Raw evidence blobs are never uploaded — they remain in the local protected evidence store, and only their hashed references are persisted to MongoDB. Migrate existing SQLite data with `python -m decode.persistence.migrate --sqlite data/decode.db`. Sending assessment data to a hosted MongoDB moves it off the local machine; treat that as a deliberate departure from the local-first default.

### Web search engine

`DECODE_SEARCH_ENGINE` selects the agent's persistent web search backend (default `duckduckgo`). The agent reaches it through `UniversalAgent.search()` and the REPL `/search <query>` command, both routed through the standard governance coordinator as a READ capability. Results are untrusted external observations: result links are never followed or executed automatically, and results are not promoted into project memory without an explicit action.

## LLMs and providers

Current provider selection supports OpenRouter (the default orchestrator), OpenAI, and Anthropic. OpenRouter is an OpenAI-compatible gateway, so a single `OPENROUTER_API_KEY` unlocks every `openrouter/*` model in the registry. A provider configuration includes provider ID, model, endpoint where applicable, credential reference, timeout, retry limit, and data policy. The OpenRouter adapter retries transient upstream failures (HTTP 429/5xx, common on shared free-tier pools) with the server's `Retry-After` hint before surfacing an error.

Future routing rules are documented in [MODEL_ROUTING.md](MODEL_ROUTING.md).

## Executors

Supported provider names include `local`, `docker`, `wsl`, `mcp`, and explicitly configured `ssh`. Executor configuration may include:

- Working directory.
- Environment allowlist.
- Timeout.
- Output size.
- Container image and mount policy.
- WSL distribution.
- SSH host, identity reference, and host-key policy.
- MCP server/client configuration.

Executor selection never changes permission policy.

## Timeouts and limits

Configure separate limits for model requests, tool execution, workflows, retries, output bytes, concurrency, scan rate, memory context, and total task budget. A timeout is mandatory for external work.

## Permissions and safety

Configuration defines:

- Scope allowlist and exclusions.
- Maximum risk.
- Destructive-action override.
- Approval callback/policy.
- Prohibited capabilities/actions.
- Allowed plugins, models, executors, and networks.
- Privilege/elevation policy.

Security ceilings cannot be lowered by a plugin, prompt, model, or task.

## Logging, audit, and telemetry

Configure locations, retention, level, redaction, rotation, and protected export. Audit cannot be disabled for executions. Optional telemetry is off by default and contains no secrets or target data without explicit consent.

## Memory

Configure storage profile, project isolation, retention, semantic retrieval, embedding provider, context budget, compression, and secret-storage integration. Semantic memory can be disabled.

## Plugins

Target plugin configuration covers approved sources, signature policy, enabled state, permissions, dependency installation policy, sandbox, and update channel. Automatic installation is disabled by default.

## Planner and agents

Configure maximum tasks, depth, iterations, concurrency, retry ceilings, model policy, agent allowlist, and per-agent memory/tool scopes.

## File format

A future project configuration may use YAML:

```yaml
version: 1
project:
  name: lab-assessment
scope:
  allowed:
    - 192.0.2.0/28
policy:
  maximum_risk: WRITE
execution:
  provider: wsl
  timeout_seconds: 600
models:
  policy: local-preferred
memory:
  semantic_search: false
```

The schema will be versioned and validated before use.

## Secrets

- Use environment variables or an OS/vault provider.
- Prefer secret references in configuration files.
- Never echo secrets in doctor/config output.
- Do not pass secrets through command-line arguments when a safer channel exists.
- Reject committed `.env` or plaintext credential files in CI.

## Validation

Startup validation reports invalid values, missing required dependencies, inaccessible paths, unsafe combinations, and degraded optional services. It displays effective non-secret configuration and source precedence.
