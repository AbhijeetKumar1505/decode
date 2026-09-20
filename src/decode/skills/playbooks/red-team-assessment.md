---
name: red-team-assessment
description: Authorized red-team assessment lifecycle with an explicit engagement gate and evidence-bound reporting.
category: exploitation
risk: READ
tags: [workflow, red-team, assessment, authorization]
target_required: true
workflow:
  version: "1"
  mode: security
  target_required: true
  stages:
    - id: authorize
      title: Confirm engagement authority
      objective: Require explicit human approval of target, rules of engagement, time window, and prohibited actions.
      execution: human
      risk: WRITE
      gate: {require_final: false}
    - id: discover
      title: Discover environment and tools
      objective: Establish target reachability, execution environment, installed tools, and applicable constraints without expanding scope.
      depends_on: [authorize]
      model_role: planner
      risk: READ
      max_steps: 10
      deliverables: [environment inventory, tool inventory, constraints]
      gate: {require_final: true, min_successful_actions: 1, require_evidence: true}
    - id: plan
      title: Build attack plan
      objective: Map bounded objectives to testable hypotheses, ATT&CK techniques, telemetry expectations, and stop conditions.
      depends_on: [discover]
      model_role: planner
      risk: READ
      max_steps: 8
      deliverables: [hypotheses, technique plan, stop conditions]
      gate: {require_final: true, min_successful_actions: 1, require_evidence: true}
    - id: execute
      title: Execute approved tests
      objective: Run the least invasive in-scope tests needed to evaluate the hypotheses.
      depends_on: [plan]
      model_role: worker
      risk: WRITE
      max_steps: 16
      instructions:
        - Recheck target scope immediately before every action.
        - Never install missing dependencies automatically.
        - Stop on denial, scope ambiguity, or unmet prerequisite.
      deliverables: [observations, raw evidence references, blocked actions]
      gate: {require_final: true, min_successful_actions: 1, require_evidence: true}
    - id: validate
      title: Validate impact
      objective: Independently challenge observed attack paths and distinguish demonstrated impact from inference.
      depends_on: [execute]
      model_role: reviewer
      risk: READ
      max_steps: 10
      deliverables: [validated findings, rejected claims, residual uncertainty]
      gate: {require_final: true, min_successful_actions: 1, require_evidence: true}
    - id: report
      title: Report and defensive handoff
      objective: Produce an evidence-linked assessment with remediation and detection opportunities.
      depends_on: [validate]
      model_role: reviewer
      risk: READ
      max_steps: 6
      deliverables: [findings, attack narrative, defensive recommendations, coverage gaps]
      gate: {require_final: true}
---

# Authorized red-team assessment

This workflow cannot authorize itself. Its first stage always pauses for a human, and every subsequent command remains subject to Decode's target allowlist, risk classification, approval binding, and audit trail.
