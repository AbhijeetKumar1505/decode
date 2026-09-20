# Workflow Architecture

**Status:** Markdown runner is Bridge; versioned YAML DSL is Target

## Principle

De-code must not depend on model memory for methodology.

```text
workflow -> phase -> task -> capability -> tool
```

Skills add guidance, not authority/state/execution/completion.

## Current bridge

`src/decode/workflows/` reads markdown frontmatter, validates dependencies,
compiles stages to `PlanGraph`, persists state, checks gates, pauses for human
stages, and resumes. Agent stages call the governed loop; definitions cannot
embed a bypass. Preserve current workflow/playbook work.

## Target definition

Versioned YAML validated by Pydantic/JSON Schema declares identity/version,
authorization/scope, phases/dependencies/actors/budgets/risk, capability
envelopes, artifacts/evidence, retry/idempotency/timeout, gates, human points,
failure/compensation, and resume behavior. Tools resolve later in the provider.

Engineering families include feature, bugfix, refactor, migration, debug,
performance, review, QA, release, docs, and security fix. Security includes
intake/scope lock, audit, threat model, red, blue, purple, hardening, detection,
incident response, remediation, and regression.

## Finding discipline and runtime

Separate inventory, attack surface, coverage, candidates, controlled validation,
independent review, remediation, regression, reporting. Candidates are never
silently confirmed.

Runner flow: validate definition; create DAG/state; schedule ready nodes; execute
through kernel; record evidence/events; check gates; pause; resume safely;
escalate material changes; complete only declared criteria.

Only independent conflict-free reads run concurrently. Automatic retry is for
explicit transient idempotent work. Consequential retry requires review.

Initial v2 promotion set: `bugfix`, `security_audit`,
`purple_validation`. gstack informs explicit engineering stages; Cloudflare's
audit skill informs coverage, validation, machine-readable findings, and review.
