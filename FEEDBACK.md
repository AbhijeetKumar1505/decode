# Feedback and Observation Policy

This file defines how coding agents respond to people and how De-code records
runtime feedback. Feedback improves decisions; it never grants authority,
changes scope, confirms a finding, or overrides evidence.

## Types of Feedback

### Corrections
If the user says something like "that's not right" or "fix this":
1. Acknowledge briefly
2. Re-read the relevant files to understand the current state
3. Apply the fix without over-explaining

### Rejections
If the user rejects a proposed approach:
1. Do not argue or justify the rejected approach
2. Ask what they'd prefer instead, or offer 1-2 alternatives
3. Implement their choice directly

### Clarifications
If the user asks "why did you do X" or "what does this do":
1. Answer in 1-3 sentences
2. Reference the specific file and line number if relevant
3. Do not expand into unrelated details

## General Rules

- Never add emojis unless the user uses them first
- Never add code comments unless requested
- When the user says "this isn't what I meant", stop and ask clarifying questions before continuing
- If you're unsure about intent, ask — don't guess

## Execution Feedback

Record a redacted observation after every attempted action, including policy
denials, dependency failures, timeouts, cancellations, parse failures, and
successful execution:

```json
{
  "capability": "network.scan",
  "provider": "wsl:kali-linux",
  "tool": "nmap",
  "status": "success",
  "duration_seconds": 11.0,
  "exit_code": 0,
  "dependency_missing": false,
  "error_category": null,
  "evidence_ref": "sha256:..."
}
```

The process exit, parser state, policy decision, and completion criteria must be
reported separately. A launched process is not automatically successful.

## Dependency Feedback

Record when a dependency check runs:

```json
{
  "tool": "nuclei",
  "provider": "wsl:kali-linux",
  "missing": true,
  "install_command": "sudo apt install nuclei",
  "attempt_install": false
}
```

Dependency feedback is informational. Installation is a separate user-approved
action and must never happen automatically.

## Agent Decision Feedback

Record a public, concise reason when the runtime selects a workflow, capability,
provider, or model role:

```json
{
  "decision": "selected_provider",
  "selected": "wsl:kali-linux",
  "reason": "authorized target tooling is available in the requested environment",
  "alternatives": ["local", "docker:decode-tools"],
  "policy_bound": true
}
```

Do not store private chain-of-thought. Store inputs, constraints, selected
option, public reason, outcome, and evidence references.

## Runtime Feedback Collection

The current implementation stores feedback under the configured runtime root;
the exact backend may evolve. Treat all feedback as potentially sensitive
operational data and keep it out of source control.

```
runtime feedback
├── execution outcomes
├── dependency observations
├── decisions and interventions
└── verification and recovery outcomes
```

Feedback may support local evaluation and optimization only under explicit data
policy. It is not automatically training data and must not be sent to a model or
external service without authorization, classification checks, and redaction.

## Workflow feedback

For each workflow stage, record the workflow and graph version, stage and node,
attempt, state transition, model/tool/provider identities, resource use,
evidence references, completion result, recovery action, and human intervention.
UTOS may use these records to optimize cost and context, but it cannot weaken
policy, evidence requirements, or completion criteria.
