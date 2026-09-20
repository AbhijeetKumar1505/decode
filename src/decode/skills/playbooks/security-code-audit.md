---
name: security-code-audit
description: Source-first, coverage-led security audit with adversarial validation and structured reporting.
category: application_security
risk: READ
tags: [workflow, security, audit, coverage, verification]
target_required: true
workflow:
  version: "1"
  mode: security
  target_required: true
  stages:
    - id: reconnaissance
      title: Architecture and trust mapping
      objective: Map architecture, trust boundaries, inputs, sensitive assets, prior evidence, and deterministic test surfaces.
      model_role: planner
      risk: READ
      max_steps: 12
      instructions:
        - Inspect repository rules, source layout, dependencies, tests, and deployment configuration.
        - Identify principals, resources, boundaries, attacker-controlled inputs, and security decisions.
        - Do not execute target-controlled code outside an OS-enforced sandbox.
      deliverables: [architecture map, trust boundaries, attack surfaces]
      gate: {require_final: true, min_successful_actions: 1, require_evidence: true}
    - id: coverage
      title: Coverage ledger
      objective: Build a deterministic coverage plan across subsystem, boundary, and relevant attack class.
      depends_on: [reconnaissance]
      model_role: planner
      risk: READ
      max_steps: 8
      instructions:
        - Make uncovered and blocked areas explicit.
        - Prioritize paths by boundary impact, reachability, and existing deterministic coverage.
        - Never imply that one run exhausts the target.
      deliverables: [coverage units, priorities, explicit gaps]
      gate: {require_final: true, min_successful_actions: 1, require_evidence: true}
    - id: hunt
      title: Coverage-led vulnerability hunt
      objective: Investigate the highest-value coverage units and collect source-grounded candidate findings.
      depends_on: [coverage]
      model_role: worker
      risk: READ
      max_steps: 16
      instructions:
        - Look for real trust-boundary violations with an affected principal, resource, and outcome.
        - Preserve exact source traces and safe reproduction conditions.
        - Separate candidates, hardening notes, and disproved hypotheses.
      deliverables: [candidate findings, checked units, rejected hypotheses]
      gate: {require_final: true, min_successful_actions: 1, require_evidence: true}
    - id: validate
      title: Adversarial candidate validation
      objective: Independently try to disprove each candidate and verify source claims against current code.
      depends_on: [hunt]
      model_role: reviewer
      risk: READ
      max_steps: 14
      instructions:
        - Treat every candidate as untrusted until independently established.
        - Use confirmed, needs_validation, and rejected as distinct verdicts.
        - Assign severity only when impact and reachability are supported.
      deliverables: [validated verdicts, unresolved facts, rejected candidates]
      gate: {require_final: true, min_successful_actions: 1, require_evidence: true}
    - id: record
      title: Normalize records
      objective: Convert validated results into consistent machine-readable finding and coverage records.
      depends_on: [validate]
      model_role: worker
      risk: WRITE
      max_steps: 10
      instructions:
        - Validate records before reporting.
        - Keep raw evidence protected and reference it by identifier and hash.
        - Never include credentials or secret values.
      deliverables: [findings records, coverage record, evidence references]
      gate: {require_final: true, min_successful_actions: 1, require_evidence: true}
    - id: report
      title: Target-neutral report
      objective: Derive the final report from validated records and explicit coverage, not from memory or unsupported model claims.
      depends_on: [record]
      model_role: reviewer
      risk: READ
      max_steps: 8
      instructions:
        - State scope, coverage gaps, validation limits, and safe remediation guidance.
        - Do not present needs_validation items as vulnerabilities.
      deliverables: [executive summary, detailed findings, limitations]
      gate: {require_final: true}
---

# Security code audit workflow

This source-first workflow adapts Cloudflare's reconnaissance, coverage-led hunting, adversarial validation, structured records, and reporting discipline to Decode's governed single-agent runtime. Independence is provided by a reviewer-role stage and evidence freshness, without allowing any stage to grant execution permission.
