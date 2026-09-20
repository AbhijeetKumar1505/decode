# Core Brain and Active Brain

**Status:** v2 Target; universal loop is migration source

## Decision locality

Core interprets authorization/goal, selects workflow/criteria, allocates budget,
creates/materially revises DAG, accepts findings, and stops/pauses. Scheduler
selects ready nodes. Active retrieves context, proposes/invokes authorized
capabilities, retries safe reads, normalizes observations, and escalates.
Verifier/Core gates finding confirmation.

## Core contract

Inputs: objective, authorization, task/workflow/DAG state, verified observations,
evidence, policy, budgets, provider health, questions. Outputs: typed workflow,
criteria, graph, budget, delegation, approval/input/replan, finding, completion,
or failure decisions with public reason and state version.

## Active contract

Receives one authorized node/capability envelope. Owns context, working memory,
governed invocation, observation, bounded recovery, local verification,
memory/evidence update, escalation. Returns Completed, NeedsApproval, NeedsInput,
NeedsReplan, Blocked, or Failed.

```text
Strategic: observe -> interpret -> decide -> delegate -> review
Operational: context -> capability -> execute -> observe -> verify -> update/escalate
```

Core does not wake for every read; Active cannot change mission. Deterministic
scheduler/policy do not require models.

Runtime states: INITIALIZING, UNDERSTANDING, PLANNING, EXECUTING, WAITING,
VERIFYING, RECOVERING, REPLANNING, AWAITING_APPROVAL, COMPLETED, FAILED,
CANCELLED.

Active escalates scope/provider changes, missing approval, repeat side effects,
workflow/criteria changes, insufficient evidence, exhausted budget, untrusted
dependencies, and user input.

Logical model roles are core, worker, reasoning, security, reviewer, summarizer,
fast. UTOS maps roles to compatible providers/models.

Migration: wrap ToolUseLoop behind Active; move state/observation services; add
deterministic workflow baseline; add Core decisions; keep direct agent as
compatibility workflow; shrink UniversalAgent after parity/migration tests.
