# De-code v2 Threat Model

**Status:** Living v2 threat model

Assets: authorization/scope, credentials, workspaces/targets/providers,
workflow/state/DAG, approvals, evidence/findings/memory, model data, budgets,
audit, and releases.

Threat sources include hostile repo/web/tool content, compromised dependencies/
extensions/MCP, target responses, mistaken/malicious users, unreliable models,
bad parsers, provider drift, remote workers, and operator error.

| Threat | Controls |
|---|---|
| model changes action | strict schema + resolved-action policy |
| false command success | exit/protocol/criteria classification |
| discover/run mismatch | provider binding |
| output outside scope | side-effect and output-path policy |
| prompt/tool injection | data separation + least privilege |
| public brief confusion | authenticated intake + scope lock |
| approval replay | digest/identity/expiry/graph version |
| duplicate retry | idempotency + review |
| evidence tampering | hashes/provenance/protected store |
| memory poisoning/leak | trust/project isolation/provenance |
| secret leakage | references/late injection/redaction |
| workflow bypass | one coordinator + conformance |
| resource exhaustion | UTOS budgets/timeouts/concurrency |
| cloud divergence | signed identity/policy + one contract |

Invariants: no direct executor, no ambient scope, non-zero failure is not success,
outputs are scoped, findings require evidence, transitions append events,
interrupted consequences need review, cloud cannot weaken policy.

Assume host/hypervisor and secret store are not fully compromised and users have
lawful authorization. Higher-risk code may require VM/microVM isolation.

Cloud IAM/multitenancy/queues/object-store/region/recovery are Deferred to AWS RFC.
