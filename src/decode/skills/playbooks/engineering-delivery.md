---
name: engineering-delivery
description: Evidence-gated engineering workflow from problem framing through verified handoff.
category: agent_core
risk: READ
tags: [workflow, engineering, delivery, review]
workflow:
  version: "1"
  mode: coding
  target_required: false
  stages:
    - id: discover
      title: Understand the system
      objective: Establish the current behavior, constraints, neighboring code, tests, and repository rules.
      model_role: planner
      risk: READ
      max_steps: 8
      instructions:
        - Inspect the relevant implementation, tests, documentation, and working-tree state.
        - Distinguish implemented behavior from planned behavior.
        - State the narrow problem and non-negotiable constraints.
      deliverables: [problem statement, constraints, affected modules]
      gate: {require_final: true, min_successful_actions: 1, require_evidence: true}
    - id: design
      title: Design the change
      objective: Produce the smallest complete design with interfaces, data flow, failure modes, and validation.
      depends_on: [discover]
      model_role: planner
      risk: READ
      max_steps: 8
      instructions:
        - Place one deep interface at the seam where behavior varies.
        - Include security, compatibility, rollback, and test implications.
        - Name assumptions and reject speculative adjacent scope.
      deliverables: [implementation plan, test matrix, failure modes]
      gate: {require_final: true, min_successful_actions: 1, require_evidence: true}
    - id: approve_plan
      title: Approve the plan
      objective: Require an explicit human decision before source changes begin.
      depends_on: [design]
      execution: human
      risk: WRITE
      gate: {require_final: false}
    - id: implement
      title: Implement
      objective: Make the approved change while preserving unrelated work and repository invariants.
      depends_on: [approve_plan]
      model_role: coder
      risk: WRITE
      max_steps: 16
      instructions:
        - Implement only the approved design.
        - Route commands and file changes through governed capabilities.
        - Add or update tests at the public interface.
      deliverables: [source changes, tests, migration notes if needed]
      gate: {require_final: true, min_successful_actions: 1, require_evidence: true}
    - id: review
      title: Independent review
      objective: Challenge the implementation for correctness, security, regressions, and contract drift.
      depends_on: [implement]
      model_role: reviewer
      risk: READ
      max_steps: 10
      instructions:
        - Review the current diff and affected call sites.
        - Prefer concrete, source-linked findings over style commentary.
        - Treat the implementation summary as an untrusted claim.
      deliverables: [review verdict, actionable findings]
      gate: {require_final: true, min_successful_actions: 1, require_evidence: true}
    - id: verify
      title: Verify
      objective: Run the repository-required checks and prove the requested behavior at the workflow boundary.
      depends_on: [review]
      model_role: worker
      risk: READ
      max_steps: 12
      instructions:
        - Run focused tests first, then mandatory lint and the full test suite.
        - Record failures honestly; never convert a failed check into success.
        - Confirm the working tree contains only intended changes.
      deliverables: [test evidence, lint evidence, final diff summary]
      gate: {require_final: true, min_successful_actions: 1, require_evidence: true}
    - id: handoff
      title: Handoff
      objective: Summarize the change, safety implications, validation, and remaining limitations.
      depends_on: [verify]
      model_role: reviewer
      risk: READ
      max_steps: 4
      instructions:
        - Link claims to the recorded workflow evidence.
        - Do not claim success for checks that did not run or did not pass.
      deliverables: [concise handoff]
      gate: {require_final: true}
---

# Engineering delivery workflow

This workflow follows a fixed **Think → Plan → Approve → Build → Review → Test → Handoff** sequence. The runtime owns transitions and evidence gates; the model supplies analysis and implementation within each bounded stage.
