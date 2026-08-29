# Decode Product Constitution

## Vision

Decode is an open-source cybersecurity agent that helps security professionals plan, execute, validate, and document authorized work across local, containerized, WSL, and remote environments.

Decode is not a chatbot with security commands attached. It is a governed tool-use agent with explicit permissions, evidence, and execution boundaries — it discovers and drives the tools already on the host rather than wrapping a fixed set.

## Mission

Build an open, extensible AI-powered cybersecurity agent capable of understanding security objectives, discovering and driving whatever tools are installed on the host, and assisting security professionals while maintaining strict safety, transparency, auditability, reproducibility, and user control.

## Problem statement

Security work is fragmented across tools, operating systems, data formats, and specialist workflows. Analysts spend substantial time translating intent into commands, switching contexts, correlating outputs, preserving evidence, and producing reports. General-purpose AI assistants add another interface but usually lack reliable tool discovery, typed execution contracts, durable security context, and enforceable safety boundaries.

Decode provides a common capability layer between human objectives and security tooling. It should make workflows easier to reproduce and inspect without hiding the commands, evidence, assumptions, or approvals that produced a result.

## Target users

- Penetration testers performing explicitly authorized assessments.
- Security researchers comparing tools, models, and planning strategies.
- SOC and incident-response analysts investigating defensive telemetry.
- Malware, forensics, cloud, identity, and application-security specialists.
- Students working in legal labs, CTFs, and controlled training environments.
- Playbook authors extending the agent with markdown procedures.
- Teams that require auditable, repeatable security automation.

## Core philosophy

1. **Authorization before action** — scope and permission checks precede execution.
2. **Human control** — consequential actions require clear review and approval.
3. **Discovery over hardcoding** — the agent discovers and drives installed tools through one governed shell capability; nothing is wrapped per-tool.
4. **Evidence over assertion** — conclusions link to collected outputs and provenance.
5. **Local first** — core workflows remain useful without mandatory hosted services.
6. **Extensibility by contract** — markdown playbooks, native capabilities, models, and executors expose typed, governed interfaces; there is no in-tree plugin loader.
7. **Reproducibility** — plans, parameters, versions, approvals, and results are recordable.
8. **Explainable decisions** — routing and planning decisions expose concise reasons, not hidden reasoning traces.
9. **Fail closed** — missing dependencies, ambiguous scope, and policy failures stop execution safely.
10. **Research honesty** — planned systems are never presented as implemented capabilities.

## Goals

- Turn authorized security objectives into an inspectable, step-by-step tool-use loop.
- Discover the tools installed across supported execution environments (`list_tools`).
- Run any installed tool or script through one governed capability (`shell_command`).
- Route work through the governed loop to the appropriate models and executors.
- Enforce permission, scope, and confirmation policies on every action.
- Preserve findings, evidence, audit events, and execution feedback.
- Support cloud and local model providers behind stable interfaces.
- Enable community extensions via markdown playbooks and native host capabilities.
- Provide deterministic replay inputs where the underlying tool permits it.
- Establish a platform for research into planning, memory, and adaptive tool use.

## Non-goals

- Fully autonomous exploitation without user-defined scope and approval gates.
- Bypassing platform protections, endpoint security, or legal authorization.
- Guaranteeing that model output is correct or that a target is secure.
- Replacing specialist judgment, evidence review, or incident command.
- Hiding raw commands, material parameters, failures, or model/provider changes.
- Training a foundation model from scratch as a prerequisite for the product.
- Hardcoding every Kali utility into the kernel.
- Collecting telemetry by default or requiring a cloud control plane.

## Core features

### Implemented

- Typer CLI and Rich/prompt_toolkit interactive REPL.
- A single governed universal agent loop (`run_tool_loop`) behind the bare prompt and `/agent`.
- Tool discovery (`list_tools`, a `$PATH` scan) — no hardcoded tool catalog.
- Governed `shell_command` / `host_session` to run any installed CLI or script as an argument vector.
- Governed host control: file read/write/edit/search, process and service operations.
- READ, WRITE, and DESTRUCTIVE per-command risk classification with `plan`/`ask`/`auto` permission modes.
- Local, Docker, WSL, SSH, and MCP execution-provider implementations.
- Markdown playbooks (`SKILL.md`) and native host capabilities as the extension paths.
- OpenRouter (default), OpenAI, and Anthropic provider adapters with data-locality-aware routing.
- SQLite (optional MongoDB) session, target, finding, evidence, project, and artifact storage.
- Audit, structured execution logging, execution feedback, and hashed immutable evidence.
- Knowledge graph with capability → MITRE ATT&CK mapping.

### Partial

- Cross-session memory and hybrid knowledge retrieval.
- Reproducible replay metadata across every execution path.
- Policy-aware model routing (built; not yet wired to planner/worker/reviewer roles).

### Planned

- Task-state spine: a live task-state schema (Neural Schema), composed prompts, and a verification/replan pass.
- Broader markdown-playbook library for common security procedures.
- Optional semantic memory retrieval.
- An isolated external-integration plugin surface (the in-tree plugin system was removed).

## Future vision

The mature platform exposes one consistent workflow across analyst workstations, Kali hosts, WSL, containers, and remote executors. A user states a scoped objective, watches the agent discover tools and choose each step, approves material actions, and receives a result linked to evidence and replay metadata.

The governed core remains small. Tool knowledge is discovered at runtime, not hardcoded; reusable procedures live in markdown playbooks; execution details belong to executors; durable state belongs to the persistence layer; and policy is enforced independently by the `ExecutionCoordinator`.

## Research objectives

- Robust tool-use planning under incomplete and changing tool availability.
- Model-routing policies that balance quality, cost, latency, and data locality.
- Knowledge-graph and semantic-memory retrieval for long-running investigations.
- Tool-output interpretation and confidence calibration.
- Prompt-injection resistance across hostile security artifacts.
- Memory compression without loss of provenance or critical evidence.
- Benchmarks based on legal labs, synthetic environments, and defensive datasets.

## Constraints

- Security tooling can be destructive, privileged, noisy, or legally restricted.
- LLM output is nondeterministic and must not be the sole authorization mechanism.
- Tool versions and output formats vary significantly across environments.
- Offline and resource-constrained deployments must remain viable.
- Secrets and sensitive assessment data require strict minimization and isolation.
- Windows, Linux, WSL, containers, and remote systems have different process models.
- Optional infrastructure must degrade gracefully when unavailable.
- Research features require measurable safeguards before production use.

## Success metrics

| Area | Measure |
|---|---|
| Safety | Zero execution paths that bypass scope and permission gates |
| Auditability | Every executed skill produces execution, audit, and feedback records |
| Reproducibility | Replay metadata captures tool version, executor, parameters, and artifact hashes |
| Capability coverage | Percentage of declared capabilities backed by healthy tools per environment |
| Reliability | Task success, retry, timeout, and recovery rates by tool and executor |
| Quality | Evidence-supported finding precision and recall on controlled benchmarks |
| Extensibility | Time and kernel changes required to add a third-party plugin |
| Model routing | Quality, latency, and cost relative to a fixed-model baseline |
| User control | Percentage of consequential actions preceded by explicit approval |
| Research | Reproducible evaluations, published datasets, and documented limitations |

## Roadmap

Release completion is tracked in the repository-level [roadmap](../ROADMAP.md). Architecture choices are recorded in [architecture decision records](adr/README.md).

Changes that conflict with this constitution require a documented architecture decision and an explicit update to this file.
