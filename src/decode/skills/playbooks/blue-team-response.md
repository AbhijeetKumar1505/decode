---
name: blue-team-response
description: Evidence-preserving incident response workflow from triage through recovery validation.
category: evidence_management
risk: READ
tags: [workflow, blue-team, incident-response, forensics]
workflow:
  version: "1"
  mode: security
  target_required: false
  stages:
    - id: authorize
      title: Confirm incident authority
      objective: Require explicit human confirmation of affected systems, evidence rules, and containment authority.
      execution: human
      risk: WRITE
      gate: {require_final: false}
    - id: triage
      title: Triage
      objective: Establish incident severity, affected assets, immediate risks, and evidence priorities.
      depends_on: [authorize]
      model_role: planner
      risk: READ
      max_steps: 10
      deliverables: [incident hypothesis, affected assets, priority questions]
      gate: {require_final: true, min_successful_actions: 1, require_evidence: true}
    - id: collect
      title: Preserve evidence
      objective: Collect the minimum relevant volatile and durable evidence with provenance and hashes.
      depends_on: [triage]
      model_role: worker
      risk: READ
      max_steps: 14
      instructions:
        - Prefer read-only acquisition and document unavoidable system impact.
        - Never expose secrets in logs or summaries.
      deliverables: [evidence inventory, provenance, collection gaps]
      gate: {require_final: true, min_successful_actions: 1, require_evidence: true}
    - id: analyze
      title: Analyze and scope
      objective: Build a supported timeline, test competing hypotheses, and determine the known blast radius.
      depends_on: [collect]
      model_role: worker
      risk: READ
      max_steps: 16
      deliverables: [timeline, supported hypotheses, indicators, scope gaps]
      gate: {require_final: true, min_successful_actions: 1, require_evidence: true}
    - id: containment_decision
      title: Approve containment
      objective: Require a human decision before any action that could disrupt systems, accounts, or evidence.
      depends_on: [analyze]
      execution: human
      risk: DESTRUCTIVE
      gate: {require_final: false}
    - id: contain
      title: Support containment and recovery
      objective: Carry out only approved, scoped response actions and document every state change.
      depends_on: [containment_decision]
      model_role: worker
      risk: WRITE
      max_steps: 12
      deliverables: [actions taken, approvals, affected assets, rollback notes]
      gate: {require_final: true, min_successful_actions: 1, require_evidence: true}
    - id: verify
      title: Verify recovery
      objective: Confirm containment effectiveness, service health, monitoring coverage, and residual risk.
      depends_on: [contain]
      model_role: reviewer
      risk: READ
      max_steps: 10
      deliverables: [recovery evidence, residual risk, monitoring plan]
      gate: {require_final: true, min_successful_actions: 1, require_evidence: true}
    - id: report
      title: Incident handoff
      objective: Produce an evidence-linked incident summary, timeline, decisions, and follow-up actions.
      depends_on: [verify]
      model_role: reviewer
      risk: READ
      max_steps: 6
      deliverables: [incident report, lessons, follow-up backlog]
      gate: {require_final: true}
---

# Blue-team incident response

Evidence preservation and human incident command are first-class gates. The workflow never treats model confidence as authority to contain, isolate, kill, revoke, or modify a production system.
