# ADR-022: Put Procedure in Versioned Workflows

**Status:** Accepted

## Decision

Use workflow → phase → task → capability → tool. Workflows own dependencies,
actors, budgets, gates, artifacts, evidence, retry, approval, resume, completion.
Skills guide only; red/blue/purple are workflow configurations.

## Consequences

Definitions need schemas, versions, migrations, fixtures, runner tests.
Markdown is Bridge; validated YAML Target.
