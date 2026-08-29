# Decode Release Roadmap

## Vision

Decode is a local-first engineering + authorized-security agent runtime: a
governed loop that turns authorized objectives into reviewable actions, enforces
scope and permission, executes through replaceable providers, and preserves
evidence and audit history. Its capabilities happen to include software
development and authorized security assessment; the runtime — not any tool set —
is the architecture.

The canonical architecture is [docs/SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md), which describes the ten De-code subsystems and their status. This file maps that design to release priorities and verified implementation state.

## De-code subsystem plan (current direction)

The target is ten subsystems (see the table in
[docs/SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md)) with a hard split
between what the model decides and what the runtime enforces. The **task-state
spine** is now in place:

1. **Task State / Neural Schema (04)** — *Implemented.* Live `TaskState` in
   `decode/schema`, read and written each turn; reuses `PlanGraph`/
   `CompletionCriterion`; persisted via `SessionStore`.
2. **Prompt composition (02)** — *Implemented.* `decode/prompting` composes the
   loop prompt from BASE + mode + capabilities + policy + task-state note.
3. **Verification Engine (10)** — *Implemented.* `decode/verification` gates a
   "done" message on completion conditions and drives bounded replan.
4. **Role→model routing (01)** — *Implemented.* `ModelGateway` maps roles to a
   provider; single-model by default, per-role overrides / opt-in routing.
5. **Coding capabilities + resolver (05, 08)** — *Implemented.* Typed git/test/
   build/patch capabilities over governed `shell_command`, a mode-aware per-turn
   resolver, and parsed coding observations.

Policy (06), Execution (07), and Artifact/Memory (09) already matched the target
and were not rewritten. Remaining enhancements: a persistent governed session
across turns (12), task-state↔evidence artifact linking (09), and an optional
reviewer-model verifier backend (10).

## Status legend

- **Implemented** — source exists and is exercised by the test suite.
- **Partial** — a working foundation exists, but required invariants are not uniformly enforced.
- **Planned** — design is documented; production implementation has not started or is incomplete.
- **Research** — requires experiments and evaluation before a product commitment.

## Verified baseline — 2026-07-31

> **Historical snapshot.** This section predates the universal-agent
> consolidation. The domain agents, tool catalog/discovery, the deterministic
> DAG planner, and the in-tree plugin system named below have since been
> **removed**; only `PlanGraph`/`PlanNode` data types remain in `planner/dag.py`.
> The current design is [docs/SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md)
> and the De-code subsystem plan above.

### Implemented

- Typer CLI and Rich + prompt_toolkit inline REPL.
- 30 auto-discovered skills spanning 20 of the 22 declared `SkillCategory` values.
- Capability registry and deterministic DAG planner.
- Recon, web, AD, credential, exploit, and reporting agents.
- Local, Docker, WSL, SSH, and MCP executor implementations.
- Provider-aware tool discovery and generated capability index.
- Mistral, OpenAI, and Anthropic model adapters.
- Scope policy and governance gate in mission/workflow execution.
- SQLite sessions, projects, targets, ports, findings, evidence, and artifacts.
- Knowledge graph, report rendering, evidence, and domain modules.
- Structured logging, audit, feedback, and dependency service foundations.
- Python 3.11+ package and CI baseline.

### Implemented P0 boundary; broader convergence remains

- Mission CLI/workflow execution, conversational registered skills, the legacy attack chain, every shipped domain CLI command, and provider-based tool discovery now share `ExecutionCoordinator`. Direct provider execution is quarantined, and domain-module subprocess, HTTP, and DNS I/O fails closed unless its action and target match the coordinator-authorized local executor context.
- Model-generated raw commands are blocked in the REPL, and the legacy raw-command API now fails closed with denial telemetry.
- The coordinator emits structured log, audit, and feedback records for every terminal outcome, and stores successful or failed execution output as an immutable protected evidence reference rather than embedding raw output in telemetry or SQLite.
- Discovered capabilities and registered legacy skills validate declared dependencies before execution. Current declarations cover required binaries and Python packages; richer service, data-file, credential-reference, and privilege profiles remain later Kali/domain integration work.
- Registered skills retain user-facing tool metadata where useful, but external command construction is owned by versioned capability adapters.
- The plugin loader imports trusted Python code in-process without manifests or isolation.
- Semantic memory and cross-session learning remain prototypes.
- Some domain modules expose useful analyzers but are not end-to-end integrations with every external platform they name.

## P0 — Execution and governance unification

**Goal:** one path from approved intent to observable execution.

**Status — complete (2026-08-07):** `ExecutionCoordinator` owns typed requests/outcomes, immediate scope/risk decisions, mandatory audit availability, stable errors, terminal telemetry, and protected evidence capture. Target-bearing contracts deny omitted or out-of-scope targets even under `allow_all`. Approval digests bind the action, target, normalized arguments, material command, executor family, risk, required privileges, opaque credential references, and an absolute expiry; mismatched, expired, future-dated, or materially changed grants fail closed. Mission/workflow, agent, REPL, attack-chain, every shipped domain CLI action, and governed provider discovery use this boundary. Direct agent, skill, capability-registry, provider, old-style plugin, raw-shell, nested cross-skill, workflow callback, dependency-install, and bootstrap-update execution is either context-bound or quarantined. Domain subprocess, HTTP, and DNS transports require the exact authorized action, local executor family, and target where applicable. Every terminal outcome emits structured log, audit, and feedback records; raw results are stored as immutable, hashed, permission-restricted evidence and telemetry carries only the reference. Table-driven and inventory tests enumerate public execution boundaries and provider call sites. Fixed, non-target health and version diagnostics remain available. P1 subsequently moved registered-skill command construction and executable coverage into the typed capability layer; guarded local-only domain compatibility transports remain explicitly non-portable.

- [x] Introduce a single execution coordinator used by mission CLI/workflows, REPL registered skills, agent dispatch, and the legacy attack chain.
- [x] Route every target action through `ScopePolicy` and `GovernanceGate` immediately before execution.
- [x] Remove or quarantine direct skill/executor bypasses.
- [x] Bind approvals to target, normalized arguments, executor, privilege, risk, and expiry.
- [x] Require dependency validation before capability resolution/execution.
- [x] Emit structured log, audit event, and execution feedback for success, failure, denial, timeout, and cancellation.
- [x] Redact secrets and preserve raw evidence by protected reference.
- [x] Add table-driven tests proving no execution entry point bypasses governance.

**Exit criteria:** all external execution is reachable only through the coordinator; coverage tests enumerate every public entry point; mandatory telemetry is complete.

## P1 — Universal capability and tool layer

**Goal:** finish the transition from tool-specific skills to capability-driven adapters.

**Status — complete (2026-08-12):** capability, normalized-argument, result, parser, adapter, discovered-tool, and discovery-report contracts are versioned at `1.0.0`. `CapabilityRegistry` resolves only registered, version-compatible adapters, normalizes typed parameters before approval, binds the exact vector and execution identity, and reuses the pinned resolution. Registered-skill command launches use adapter vectors rather than shell strings; Nmap, WhatWeb, and Gobuster share normalized parsers with stable partial warnings and unchanged raw output. Unknown tool versions are explicitly `unverified`; detected unsupported Nmap majors fail closed. Adapter rules resolve argument-sensitive risk before governance, including destructive classification for Masscan rates above 5,000 packets per second. Provider transports preserve vectors or structured calls and record tool, adapter, parser, executor, platform, architecture, schema, and environment versions. `EnvironmentScanner` is now a compatibility view over `DiscoveryEngine`; discovery publishes separate installed and executable indexes plus provider/domain coverage, so installed-but-unsupported tools never count. Inventory tests enforce that agents name no concrete tools and external command launches in registered skill files consume adapter vectors.

- [x] Version capability, normalized argument, result, and parser schemas.
- [x] Move command construction out of agents and skills into adapters.
- [x] Add argument-sensitive risk metadata.
- [x] Record tool, adapter, parser, executor, and environment versions.
- [x] Add parser fixtures for malformed, partial, localized, and unsupported output.
- [x] Consolidate the legacy host scanner with `DiscoveryEngine`.
- [x] Report capability coverage by provider and domain.

**Exit criteria:** agents never name tools; installed-but-unsupported tools do not count as executable coverage; raw output survives parse failures.

## P2 — Plugin SDK and trust model

> **Withdrawn (removed 2026-08-28).** The manifest, sandbox, lifecycle, and
> in-process loader (`decode/plugins/`, `decode/tools.py`) shipped but were never
> exposed as a governed execution path, and encoded the old in-tree-tools model.
> They have been deleted. Extension is now via markdown playbooks and native
> capabilities; an *external-integration* plugin surface is planned but unbuilt
> (see [docs/PLUGIN_MANIFEST.md](docs/PLUGIN_MANIFEST.md)). The checklist below is
> retained as a record of what was built and removed.

**Goal:** support extensions without treating arbitrary third-party code as trusted kernel code.

- [x] Versioned plugin manifest and compatibility contract.
- [x] Declared capability, dependency, platform, permission, and sandbox requirements.
- [x] Persisted install, verify, enable, disable, upgrade, rollback, and uninstall lifecycle.
- [x] Restricted container profile for untrusted extensions (network-disabled pending scoped-container networking).
- [x] Plugin conformance and policy-violation tests.
- [x] Source-pinned entrypoint distribution and local revocation policy.

**Exit criteria:** a third-party plugin can be disabled without kernel changes and cannot broaden its granted permissions.

## P3 — Planning, recovery, and memory

**Goal:** durable, evidence-aware multi-step missions.

**Status — complete (2026-08-23):** plan nodes carry typed `CompletionCriterion` entries that the mission runner validates against agent results before a node is allowed to succeed; a failed criterion demotes the node to `error` rather than reporting false success. Nodes declare a `RetryCategory` (only `transient_read` may auto-retry, bounded by `max_attempts`) and an optional idempotency key. Plans and per-node state persist to SQLite; on resume, work interrupted while `running` is fenced to `needs_review` — never replayed automatically — satisfying the exit criterion. Each node carries a material fingerprint over capability, params, completion, retry category, and idempotency key; a materially changed node is reset to `pending` and reported through `MissionReport.approval_invalidated_nodes`, so a prior approval never carries across a material change. Memory is project-isolated: a per-project knowledge graph (nodes/edges) plus durable artifacts, retrieved through a hybrid exact/graph/optional-semantic retriever that preserves per-record provenance and cannot cross project boundaries. Retention controls cover export (with sensitive redaction), compression, and deletion, each recorded as a `memory_event`. Optional semantic retrieval remains a pluggable, unverified prototype.

- [x] Typed completion criteria and validation per plan node.
- [x] Safe retry categories, idempotency keys, cancellation, and resume boundaries.
- [x] Adaptive re-planning that invalidates approvals when execution changes materially.
- [x] Project-isolated knowledge graph integration.
- [x] Hybrid exact/graph/optional semantic retrieval with provenance.
- [x] Memory retention, export, compression, and deletion controls.

**Exit criteria:** interrupted controlled-lab missions resume from a persisted safe boundary without repeating ambiguous consequential actions.

## P4 — Agent and model orchestration

**Goal:** bounded specialization and policy-aware model choice.

**Status — complete (2026-08-23):** `AgentDescriptor` is a versioned, extra-forbidding envelope declaring capabilities, maximum risk (computed from the registered risk of an agent's capabilities so it can never under-declare), memory read/write scopes, required model capabilities, and limits (timeout, retries, token budget, delegation depth). `AgentManager.validate()` rejects invalid envelopes and any capability owned by two agents. `descriptor.delegate()` derives a child that is a strict subset of its parent and raises if it would add a capability, raise risk, raise the token budget, add a memory scope, or exceed the remaining delegation depth. The `ModelRegistry` declares per-model capabilities, data policy (max classification, locality, retention), context limit, versioned cost, latency class, task-quality scores, availability, and fallback group; it ships metadata for the three implemented hosted providers (local runtimes remain planned, so `local_only` fails closed with a clear reason). `ModelRouter` applies safety/data as hard filters and quality/latency/cost as ranked optimizers, honors declarative versioned rules (e.g. confidential→local, planning→structured_output), pins reproducibly, and records a concise public reason plus matched rules. Fallback re-runs inference only within the same fallback group, never crossing a locality boundary or lowering data trust, and never repeats a tool action. `UniversalAgent.select_model()` exposes this at runtime with availability gated by configured credentials. Offline evaluation datasets and deterministic scorers cover planning, structured output, evidence use (no fabricated citations), and prompt-injection resistance. The shipped chat path still defaults to the configured provider; the router is the reproducible, explainable selector for task-scoped model choice.

- [x] Versioned agent descriptors with tool, model, memory, scope, and budget limits.
- [x] Delegation with a strict subset of parent authority.
- [x] Model registry for capability, locality, data policy, context, quality, latency, and cost.
- [x] Safe fallback that never crosses data-policy boundaries or repeats tool actions.
- [x] Evaluation datasets for planning, structured output, evidence use, and prompt injection.

**Exit criteria:** agent/model selection is reproducible and records concise public reasons without exposing private chain-of-thought.

## P5 — Kali coverage and reproducibility

**Goal:** reliable capability coverage across native Kali, WSL, Docker, and configured SSH hosts.

**Status — complete (2026-08-23):** normalized, version-aware parsers now cover Nmap, WhatWeb, Gobuster, httpx, Nuclei, ffuf, RustScan, Masscan, Subfinder, Amass, AD/SMB (enum4linux), and offline credential audit (john). httpx and Nuclei emit machine-readable JSON/JSONL; every parser preserves raw output, labels partial results, and flags a non-zero tool exit. The offline credential-audit parser is secret-safe: it reports cracked/remaining counts, affected account names, and weak-secret counts but never emits plaintext. Each adapter declares `supported_major_versions` (off-version tools fail closed as `unsupported`, unknown versions report `unverified`), and published compatibility fixtures under `tests/fixtures/kali` drive success, partial, and malformed cases. `DiscoveryEngine.discover_resources()` inventories privileges (root/sudo/raw-socket), wordlists, template packs, exploit databases, and auxiliary services into `DiscoveryReport.resources`. `ReplayRecord` (`decode/replay.py`) binds the exact material command and tool/adapter/parser/environment identity to the evidence SHA-256, producing a stable `replay_id` for reproducibility. A controlled, network-isolated lab (`docker/lab/docker-compose.yml`) plus opt-in integration tests (`tests/integration/test_lab.py`, gated by `DECODE_LAB=1`) exercise supported capabilities against an authorized target without touching the unit suite.

- [x] Prioritize Nmap, httpx, Nuclei, ffuf, Gobuster, RustScan, Masscan, Amass, Subfinder, AD/SMB, and offline credential-audit adapters.
- [x] Discover privileges, templates, wordlists, databases, and auxiliary services.
- [x] Pin supported tool/parser versions and publish compatibility fixtures.
- [x] Capture replay metadata and evidence hashes.
- [x] Maintain controlled lab images for integration testing.

**Exit criteria:** supported capabilities produce equivalent normalized results across documented environments within declared limits.

## P6 — Optional team and distributed profile

**Goal:** scale without weakening local-first security invariants.

- [ ] Versioned FastAPI control plane with project authorization.
- [ ] PostgreSQL shared operational state and tested migrations.
- [ ] In-process event schemas before optional Redis Streams transport.
- [ ] Protected object storage and optional Qdrant/pgvector retrieval.
- [ ] Signed worker identity, heartbeat, cancellation, and remote policy bundles.
- [ ] Tenant isolation, rate limits, backup/restore, and incident procedures.

**Exit criteria:** failure and scale tests demonstrate the same scope, approval, audit, and data-isolation guarantees as local mode.

## Research track

- Neural Schema representation, evaluation, rollback, and poisoning resistance.
- Fine-tuning versus retrieval/routing baselines.
- Memory compression with provenance preservation.
- Security-agent and tool-selection benchmarks.
- Multi-agent conflict resolution and least-privilege delegation.

Research work does not enter production until it has held-out quality results, safety regression tests, a rollback path, and documented data rights.

## Release gates

Every release requires:

- `ruff check .`
- `ruff format --check .` after establishing a dedicated repository-wide formatting baseline.
- `python -m pytest tests/`
- Scope, permission, denial, timeout, and secret-redaction tests.
- Documentation link and path validation.
- Migration and rollback notes where state changes.
- Updated maturity labels in canonical documentation.
- No planned capability described as implemented.
- One authoritative release version across package metadata, CLI output, documentation, and changelog.

## Community input

Use GitHub issues and focused pull requests to propose capabilities, adapters, tests, ADRs, or research evaluations. Security-sensitive design changes should reference [the security model](docs/SECURITY_MODEL.md) and an applicable [architecture decision](docs/adr/README.md).
