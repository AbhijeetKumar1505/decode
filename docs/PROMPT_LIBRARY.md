# Prompt and Model-Interaction Contracts

**Status:** Current composer is foundation; strict schemas are Phase 0

Prompts guide models; they are not application logic/security boundaries.
Workflow, policy, state, schemas, and verification remain runtime contracts.

Provide only relevant objective, phase/node, criteria, state summary, scope/
policy, full capability JSON Schemas, budget, provenance-labeled observations,
and open questions. Tool/memory/web content is untrusted.

Use native structured calls or strict JSON. Reject unknown/wrong fields, multiple
unsupported calls, shell syntax in vector mode, and unregistered capabilities.
Never silently ignore `filter` when schema says `query`.

Request concise public decisions; do not require/store private chain-of-thought.
Store typed decision inputs, rule matches, and evidence for replay.

Prompt classes: Core strategy, Active operation, security hypothesis, independent
reviewer, summarizer, final reporter. Each has version, role, I/O schema, data
class, budget, tests, owner.

Defend injection with labels/delimiters, data minimization, fixed authority,
output validation, and malicious repo/web/tool/memory/MCP tests. Evaluate schema
errors, conflicts, abstention, scope ambiguity, and truncation.
