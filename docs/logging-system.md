# Structured Logging

**Status:** Diagnostics distinct from audit/evidence/events

Logs diagnose runtime behavior; they do not authorize, prove evidence, or replace
audit.

Record timestamp, level, module, task/workflow/node/request ids, provider,
capability, public code, duration, retries, and redacted error. Use structured
fields.

Never log secrets/cookies/tokens/keys/sensitive stdin. Reference evidence for
large/raw output. Preserve unknown/null. Correlate model/tool/policy/state/
verification. Bound traces/payloads and treat sinks as failure surfaces.

Logs are diagnostics; audit is accountability; evidence is factual artifact;
events are durable state; usage is UTOS accounting. Retention is conservative,
project-scoped, rotated/exported/deleted under audit. Cloud logging is Deferred.
