# Configuration Templates

Runtime configuration is loaded from `.env` and environment variables by `decode/config.py`. Copy the root `.env.example` to `.env`; do not commit the populated file.

## Model provider

| Variable | Default | Meaning |
|---|---|---|
| `DECODE_PROVIDER` | `mistral` | Selected provider: `mistral`, `openai`, or `anthropic` |
| `MISTRAL_API_KEY` | none | Mistral credential |
| `DECODE_MODEL` | `mistral-large-latest` | Mistral model |
| `OPENAI_API_KEY` | none | OpenAI credential |
| `OPENAI_MODEL` | `gpt-4o` | OpenAI model |
| `ANTHROPIC_API_KEY` | none | Anthropic credential |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | Anthropic model |

The CLI `--provider` option overrides `DECODE_PROVIDER` for that invocation. Startup validates the credential for the selected provider rather than always requiring Mistral.

## Operational paths

| Variable | Default |
|---|---|
| `DECODE_EXECUTOR` | `local` |
| `MAX_ITERATIONS` | `20` |
| `MEMORY_PATH` | `./data/models/` |
| `LOGS_PATH` | `./logs/` |
| `AUDIT_PATH` | `./audit/` |
| `FEEDBACK_PATH` | `./feedback/` |
| `TOOL_REGISTRY_PATH` | `./data/tool_registry.json` |
| `PROFILES_PATH` | `./profiles/` |

Local execution affects the host. Docker, WSL, SSH, and MCP require their own provider configuration and do not grant scope or permission. See [the full configuration specification](../docs/CONFIGURATION.md).
