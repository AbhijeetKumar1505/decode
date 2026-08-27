# Prompt Library

## Principle

Prompts are versioned product behavior. Reusable prompts must live in the prompt library rather than being scattered through agents, skills, or route handlers.

## Current structure

```text
prompts/
  system/
    universal_agent.yaml
  domains/
    cloud.yaml
    malware.yaml
    redteam.yaml
```

`decode/prompt_engine.py` loads domain prompts. Some older code paths may still construct prompt text directly; migration to the library is ongoing.

## Prompt classes

| Prompt | Purpose |
|---|---|
| Planner | Produce typed, dependency-aware task proposals |
| Architect | Analyze system structure and tradeoffs |
| Researcher | Synthesize evidence with citations and uncertainty |
| Security analyst | Correlate findings and defensive context |
| Code reviewer | Identify evidence-linked code security defects |
| Pentester | Assist authorized, scoped assessment workflows |
| Forensics | Analyze artifacts while preserving provenance |
| Malware analyst | Perform bounded static/dynamic analysis |
| SOC analyst | Triage and correlate defensive alerts |
| Summarizer | Compress context without losing critical decisions or evidence links |

## Prompt package

Each prompt definition should include:

```yaml
id: planner.default
version: 1
role: planner
purpose: Build a capability task graph
inputs:
  - objective
  - scope
  - capability_catalog
output_schema: PlanGraph
data_policy:
  maximum_classification: confidential
safety:
  tool_execution: forbidden
  permission_decision: forbidden
tests:
  - planner_scope_preservation
  - planner_unknown_capability
```

## Required boundaries

- Trusted policy is separate from user and retrieved content.
- External artifacts are clearly delimited and labeled untrusted.
- Prompts request capability IDs, not raw shell commands, unless command construction is the tested purpose.
- Models cannot approve actions or alter scope.
- Output schemas are validated.
- Secret values are excluded unless required by an approved action.
- Private reasoning traces are not requested or stored; concise decision reasons are.

## Variables

Variables have typed definitions, maximum lengths, required/optional state, and safe defaults. Free-form values are escaped or placed in structured message fields.

Never substitute untrusted values into trusted instruction text.

## Versioning

- Prompt IDs are stable.
- Material behavior changes increment the version.
- Sessions and evaluations record prompt version.
- Running workflows remain pinned.
- Rollback preserves prior packages.
- Deprecated prompts have a documented replacement.

## Testing

Every material prompt requires:

- Golden structured-output fixtures.
- Invalid/malformed output handling.
- Direct and indirect prompt-injection cases.
- Scope-preservation checks.
- Secret-exfiltration checks.
- Model/provider comparison where supported.
- Regression thresholds for correctness and refusal behavior.

Snapshot text alone is insufficient; tests validate semantic constraints.

## Evaluation

Measure schema validity, task correctness, unsupported claims, evidence citation, scope adherence, unsafe action proposal rate, latency, and cost. Dataset items use legal synthetic or approved sources.

## Change process

1. State the behavior change.
2. Update the prompt package and version.
3. Add or update evaluation cases.
4. Run supported model evaluations.
5. Review safety and quality deltas.
6. Document migration/rollback.
7. Release with provenance.

## Logging

Record prompt ID/version, model ID, token usage, and safe input artifact references. Do not log secret values or unrestricted prompt contents by default.
