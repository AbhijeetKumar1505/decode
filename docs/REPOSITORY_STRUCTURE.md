# Repository Structure and Migration Map

**Status:** Target layout with incremental migration

## Current

```text
src/decode/
  app/ runtime/ governance/ hostcontrol/ execution/ capabilities/
  workflows/ planner/ schema/ verification/ models/ memory/
  persistence/ observability/ extensions/
```

This Python package remains executable source truth.

## Target

```text
apps/decode-cli/          TypeScript client
apps/decode-desktop/      later client
services/decode-runtime/  Python runtime/API
packages/                 shared contracts
workflows/                schemas + engineering/security/shared definitions
policies/ schemas/
deployments/              linux/wsl/docker/security/aws(deferred)
tests/                    unit/integration/security/evaluation/conformance
docs/
```

Target runtime packages: api, core, brain, planning, workflows, execution, tools,
models, utos, memory, security, verification, storage, observability, auth.

## Mapping

| Current | Target |
|---|---|
| `runtime/coordinator.py` | `execution/coordinator.py` |
| `hostcontrol/`, host controller | execution + tools |
| `execution/` | execution/environments |
| agent loop | active_brain/runtime |
| universal agent | composition root |
| `planner/` | planning/scheduler |
| `workflows/` | runtime package + root YAML |
| task state | versioned core/shared schema |
| models/routing | model gateway + UTOS routing |
| memory/knowledge | unified provenance memory |
| persistence | storage/repositories/migrations |
| Python app | TS CLI client after API parity |

## Rules

No big-bang move. Add contracts at seams, migrate one vertical slice with
compatibility, version state migrations, require CLI parity, remove compatibility
after two releases, and keep AWS deferred.

Core chooses but cannot execute. Active executes but cannot expand authority.
Workflows request capabilities but cannot bypass. Kernel authorizes exact actions.
Tools adapt but do not decide policy. UTOS allocates but cannot weaken safety.
Interfaces render state but are not authorities.
