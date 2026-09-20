---
name: purple-team-validation
description: Joint attack-and-detection validation loop with measurable coverage and safe retesting.
category: attack_graph
risk: READ
tags: [workflow, purple-team, detection, validation]
target_required: true
workflow:
  version: "1"
  mode: security
  target_required: true
  stages:
    - id: authorize
      title: Confirm exercise authority
      objective: Require explicit approval of target, test identities, telemetry sources, safety controls, and cleanup expectations.
      execution: human
      risk: WRITE
      gate: {require_final: false}
    - id: baseline
      title: Baseline controls and telemetry
      objective: Record expected prevention, detection, logging, alerting, and response behavior before simulation.
      depends_on: [authorize]
      model_role: planner
      risk: READ
      max_steps: 10
      deliverables: [control baseline, telemetry map, success criteria]
      gate: {require_final: true, min_successful_actions: 1, require_evidence: true}
    - id: emulate
      title: Emulate bounded behavior
      objective: Execute the approved atomic behavior or adversary step with identifiers that support correlation and cleanup.
      depends_on: [baseline]
      model_role: worker
      risk: WRITE
      max_steps: 12
      instructions:
        - Prefer installed, well-understood atomic tests in a controlled environment.
        - Check prerequisites separately and never auto-install them.
        - Record cleanup and stop conditions before execution.
      deliverables: [execution evidence, correlation identifiers, cleanup status]
      gate: {require_final: true, min_successful_actions: 1, require_evidence: true}
    - id: observe
      title: Collect defensive observations
      objective: Gather prevention, detection, telemetry, triage, and response observations linked to the emulation identifiers.
      depends_on: [emulate]
      model_role: worker
      risk: READ
      max_steps: 12
      deliverables: [alerts, telemetry, prevention outcome, response timing]
      gate: {require_final: true, min_successful_actions: 1, require_evidence: true}
    - id: assess
      title: Assess coverage
      objective: Compare observed defensive behavior with the declared success criteria and identify root-cause gaps.
      depends_on: [observe]
      model_role: reviewer
      risk: READ
      max_steps: 10
      deliverables: [coverage verdict, gaps, false positives, root causes]
      gate: {require_final: true, min_successful_actions: 1, require_evidence: true}
    - id: improve
      title: Improve controls
      objective: Implement the smallest approved detection, prevention, or response change that addresses a validated gap.
      depends_on: [assess]
      model_role: coder
      risk: WRITE
      max_steps: 14
      deliverables: [control changes, tests, rollback notes]
      gate: {require_final: true, min_successful_actions: 1, require_evidence: true}
    - id: retest
      title: Retest
      objective: Repeat the same bounded behavior and prove whether the control change improved the measured outcome.
      depends_on: [improve]
      model_role: reviewer
      risk: WRITE
      max_steps: 12
      deliverables: [before-after evidence, regression checks, residual gaps]
      gate: {require_final: true, min_successful_actions: 1, require_evidence: true}
    - id: report
      title: Coverage handoff
      objective: Record technique coverage, evidence, control changes, residual risk, and the next validation cycle.
      depends_on: [retest]
      model_role: reviewer
      risk: READ
      max_steps: 6
      deliverables: [coverage report, evidence links, residual backlog]
      gate: {require_final: true}
---

# Purple-team validation

This is a closed-loop workflow: **baseline → emulate → observe → assess → improve → retest**. Attack activity and defensive evidence stay correlated, so the result is a measured control outcome rather than a model-written narrative.
