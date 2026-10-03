# Configuration Templates

Runtime configuration is loaded from `.env` and environment variables by `src/decode/app/config.py`. Copy the root `.env.example` to `.env`; do not commit the populated file.

## Model provider

| Variable | Default | Meaning |
|---|---|---|
| `DECODE_PROVIDER` | `openrouter` | Selected provider: `openrouter`, `openai`, `anthropic`, `mistral`, or `bedrock` |
| `OPENROUTER_API_KEY` | none | OpenRouter credential |
| `MISTRAL_API_KEY` | none | Mistral credential |
| `DECODE_MODEL` | `openrouter/free` | Config/OpenRouter default model identifier |
| `OPENAI_API_KEY` | none | OpenAI credential |
| `OPENAI_MODEL` | `gpt-4o` | OpenAI provider default model |
| `ANTHROPIC_API_KEY` | none | Anthropic credential |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | Anthropic provider default model |
| `AWS_ACCESS_KEY_ID` | none | Bedrock configured-credential check; transport uses the AWS credential chain |

The CLI `--provider` option overrides `DECODE_PROVIDER` for that invocation. Startup validates the credential for the selected provider rather than always requiring Mistral.

## Operational paths

| Variable | Default |
|---|---|
| `DECODE_HOME` | `~/.decode` |
| `DECODE_EXECUTOR` | `local` |
| `MAX_ITERATIONS` | `20` |
| `MEMORY_PATH` | `<DECODE_HOME>/data/models` |
| `LOGS_PATH` | `<DECODE_HOME>/logs` |
| `AUDIT_PATH` | `<DECODE_HOME>/audit` |
| `FEEDBACK_PATH` | `<DECODE_HOME>/feedback` |
| `EVIDENCE_PATH` | `<DECODE_HOME>/evidence` |
| `TOOL_REGISTRY_PATH` | `<DECODE_HOME>/data/tool_registry.json` (compatibility configuration, not a hardcoded tool catalog) |
| `PROFILES_PATH` | `<DECODE_HOME>/profiles` |

Local execution affects the host. Docker, WSL, SSH, and MCP require their own provider configuration and do not grant scope or permission. See [the full configuration specification](../docs/CONFIGURATION.md).
