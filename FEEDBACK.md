# Feedback Handling for Coding Agents

This file defines how AI coding agents should respond to user feedback during a session.

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

Record after every tool execution:

```json
{
  "tool": "nmap",
  "status": "success",
  "runtime": 11.0,
  "dependency_missing": false,
  "error": ""
}
```

## Dependency Feedback

Record when a dependency check runs:

```json
{
  "tool": "nuclei",
  "missing": true,
  "install_command": "sudo apt install nuclei",
  "attempt_install": false,
  "install_success": false
}
```

## Agent Decision Feedback

Record when the planner selects a skill:

```json
{
  "planner": "selected_nmap",
  "confidence": 0.91,
  "alternatives": ["nuclei", "whatweb"],
  "execution_time": 2.3,
  "success": true
}
```

## Runtime Feedback Collection

Feedback is stored in `feedback/` as JSONL files:

```
feedback/
├── execution.jsonl
├── dependencies.jsonl
└── decisions.jsonl
```

These are used as training data for future capability optimization.
