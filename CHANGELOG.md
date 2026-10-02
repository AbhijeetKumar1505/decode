# Changelog

## Unreleased

- Hardened Phase 2 launch boundaries: scope reset preserves existing guards;
  awaited preparation precedes final governance and effective approval-expiry
  checks; host restrictions and provider/session bindings are revalidated at
  launch. Dependency material mutations invalidate bound context, and cancelled
  actions retain their governed request IDs in Active handoff. Added regressions
  for these paths, including actual host-policy revocation and shorter grants.

- Implemented the bounded Phase 2 Active runtime over the workflow Bridge:
  shared context, working observations, local gates, and durable typed handoff
  for model-driven and model-free READ stages. Completion requires protected
  governed evidence; no-action finals, errors, cancellation, and budgets cannot
  silently complete. Failed model actions stop without automatic retry;
  material/provider changes require review, including changes during approval.
  Durable state refreshes between
  nodes so bounded dependency evidence reaches the next stage. Added offline
  lifecycle regressions and opt-in live Kali WSL/Docker stage conformance.
  Windows, native Kali, and live WSL/Docker stage gates passed after a
  user-authorized host-engine recovery; the failure history is retained.
- Added a narrow evidence-bound file-artifact gate: an absolute declared path
  and SHA-256 must match one protected governed read (and byte length when
  declared). Active observations store only the path fingerprint; a same-byte
  file at another path cannot satisfy the criterion.
- Added bounded, fingerprint-checked dependency evidence references to Active
  stage context and typed escalation categories for incomplete Active results.
  Preflight/material-change refusals retain governed request provenance;
  older saved incomplete results load with an explicit unknown category.
- Carried coordinator-originated action provenance into model-driven workflow
  stages and stopped accepting model-loop step text or loose task artifacts as
  action/evidence counts. Added an exact file byte-length gate that can be
  paired with SHA-256 on the same protected read observation; denied-only
  model stages now pause despite a final answer.
- Added a typed, provenance-bearing Active-node record for governed model-free
  READ stages and an exact evidence-linked file SHA-256 workflow gate. The
  runner checks node binding and gate consistency before checkpointing; raw
  file content is excluded from this record.
- Added a programmatic model-free workflow Bridge for one exact, scoped READ
  host action. It uses the existing governance/evidence/telemetry path, returns
  typed stage outcomes, retries only an explicitly permitted timeout once, and
  pauses when the deterministic stage gate is unmet. CLI exposure and broader
  capabilities remain future work.
- Bound both stage adapters to a typed snapshot of the durable workflow plan,
  bounded and redacted model context, and tightened the READ retry classifier
  to require an unchanged action and an unambiguous timeout. Model-free
  preflight denials now retain audit, log, and feedback records without
  executing the rejected action.
- Completed the Phase 1 governed task gate on local Linux, Kali WSL, and
  Docker: automatic sanitized checkpoints, safe same-task resume, verified
  evidence links, and mandatory execution telemetry. Failed checkpoints stop
  the loop; unresolved actions require manual review.
- Recovered WSL provider discovery from stale inherited PATH directories
  without accepting a failed partial scan as a complete inventory.

- Added governed exact-tool inspection with a provider-local SHA-256 fingerprint
  and PATH-only discovery. Governed CLI and external-provider session actions
  now bind absolute executable paths and SHA-256 digests to approval and recheck
  them immediately before launch; semantic tool version remains follow-up work.
- Bound local session commands to their captured PATH, exact executable
  fingerprint, cwd, environment hash, and declared outputs. Local `cd` binds
  its next cwd; changed executable or session context blocks launch.
- Corrected Docker wait-result classification: API errors are no longer reported
  as timeouts, malformed statuses fail, and available partial output is kept.
  Explicit create/start now cleans up start failures and never implicitly pulls
  a missing image. Added offline outcome checks and opt-in live Kali WSL/Docker
  conformance tests.

- Exposed exact-provider path mappings through `DECODE_PROVIDER_MAPPINGS` for
  the universal agent and interactive host controller. Mappings default to
  read-only and do not bypass filesystem scope or command approval.

### Fixed

- Declared completion conditions now fail closed when bounded replanning is
  exhausted: the task checkpoints as blocked and returns failed criteria
  instead of accepting an unsupported final answer.
- Replaced dynamic artifact INSERT, SELECT, and UPDATE SQL construction with
  fixed statements or fixed query fragments and bound values; added a
  SQL-metacharacter regression test. Kept the CI security scan enforced.
- Completed the Phase 0 execution-truth gate: non-zero host commands now fail;
  tool schemas are strict and visible; shell operators/interpreters are rejected
  in vector mode; explicit command outputs are WRITE-classified and
  filesystem-scoped; filtered discovery matches are no longer hidden by the old
  1,500-character observation cutoff; and malformed tool parameters fail closed.
- Bound `list_tools` and `shell_command` to the same selected execution provider,
  including qualified `wsl/<distribution>` identities. Verified the real
  `wsl/kali-linux` path by discovering and executing `uname` through Decode.
- Bound recognizable network CLI targets and required target-bearing MCP schemas
  to the engagement allowlist before provider execution. Browser executables
  remain CLI tools, not implicit semantic browser/search capabilities.
- Closed the legacy session branch around strict validation: session lifecycle
  arguments now use typed schemas, cwd/output paths cross filesystem scope, and
  network commands inside sessions fail closed in favor of target-aware
  `shell_command`.
- Hardened native Windows operation: protected evidence uses a current-user-only
  DACL, MCP telemetry honors configured runtime paths, SQLite session ordering is
  deterministic when timestamps tie, and test stores close before temporary
  directory cleanup.

### Documentation

- Reconciled every root and `docs/` Markdown file with the De-code v2 thesis:
  model as cognition; runtime as authority; workflow as procedure; evidence as
  truth.
- Added the canonical phased build plan, continuation ledger, repository
  migration map, Core/Active Brain contract, workflow architecture, UTOS design,
  and architecture decisions for the transition.
- Standardized maturity labels as Current, Bridge, Target, Research, and
  Deferred so planned systems are not presented as implemented.
- Made Phase 0 execution truth and safety the next release gate, including
  process-result correctness, strict schemas, output scope/risk, provider-bound
  discovery/execution, exact discovery, and governed browser/search contracts.
- Deferred AWS topology and service selection until local Linux, Kali WSL, and
  Docker gates pass and the user creates the AWS project.

### Removed

- Deleted the orphaned in-tree plugin/tools/planner layer: `decode/tools.py` (`PluginManager`/`ToolRegistry`), the `decode/plugins/` package (manifest, sandbox, lifecycle, and the bundled `recon`/`web`/`network`/`exploit` plugins), the legacy `decode/kernel/planner.py` (`Workflow`/`Planner`), and the test-only `decode/planner/planner.py` (`DAGPlanner`), with their tests. None were on the live agent-loop path. The `PlanGraph`/`PlanNode`/`CompletionCriterion` data types in `decode/planner/dag.py` are retained (used by `HostController`). Skill discovery no longer scans `decode.plugins`.
- Superseded the earlier ten-subsystem documentation with the v2 workflow-first
  plan. Extension remains based on markdown playbooks, native capabilities,
  declarative plugin packages, and governed MCP providers. ADR-004 remains
  superseded.
- Removed the dead `build_stdio_client` stub in `decode/execution/mcp.py` (it raised `NotImplementedError` and had no callers). The real MCP client is built by `decode.extensions.mcp_client.build_client`.
- Deleted the leftover empty `decode/plugins/` directory (stale bytecode from the removed plugin layer; no tracked source).

### Changed

- Runtime output trees (`evidence/`, `audit/`, `feedback/`, `logs/`) and volatile `data/` files (session/workflow dumps, history, `bootstrap_report.json`, `tool_registry.json`, SQLite `-shm`/`-wal`) are now git-ignored and untracked; curated `data/evaluations/` and `data/initial_knowledge.json` stay tracked. `.gitkeep` placeholders preserve the runtime directories.
- Declared `mcp` as an optional install extra (`pip install .[mcp]` / `poetry install -E mcp`); the real MCP transport supports `stdio` only (`http`/`sse` fail closed).

### Changed

- Per-turn tool surfacing now distinguishes general-purpose (engineering) playbooks from security-domain ones: playbooks whose `category` is in `GENERAL_SKILL_CATEGORIES` (currently `agent_core`, also the default) are offered in **every** task mode, including `CODING`, while security-domain playbooks (e.g. `web_scanning`) stay gated to `SECURITY`/`HYBRID`. Implemented in `decode/capabilities/registry.py` (`CapabilityRegistry.resolve`), mirrored in `decode/capabilities/resolver.py`, with the skill `category` threaded through `build_registry`/`Capability` and the descriptor built in `decode/universal_agent.py`. This makes the vendored engineering playbooks (TDD, code review, etc.) available during coding tasks.

### Added

- Began the Phase 1 execution-kernel contract with typed environment identity,
  capability declarations, filesystem modes, and fail-closed host-to-provider
  path mappings for local, WSL, Docker, SSH, and MCP providers.
- Added typed provider execution context for cwd, environment, and declared
  outputs; configured external providers now bind mapped outputs to native
  transports while unmapped or read-only paths remain denied.
- Added provider-bound context-persistent sessions for local, WSL, and SSH with
  immutable session/provider identity, mapped cwd transitions, per-command
  governance, approval-bound outputs, and scope/mapping revalidation. Docker and
  MCP sessions remain disabled.
- Added a typed resolved action for governed CLI and provider session commands.
  Exact argv, target, mapped outputs, known side effects, timeout, idempotency,
  and evidence/parser policy are approval-bound; redacted approval details and
  privacy-safe telemetry summaries preserve the same action identity.
- Vendored the [mattpocock/skills](https://github.com/mattpocock/skills) engineering, productivity, and misc sets as 29 markdown playbooks in `decode/skills/playbooks/` (TDD, code review, domain modeling, bug diagnosis, to-spec/to-tickets, grilling, wizard, and more). Each upstream skill is imported as one consolidated `.md` (companion reference files inlined so `rglob` discovery does not register them as separate playbooks) with frontmatter conformed to Decode's schema (`category: agent_core`, `risk: READ`, tags include `mattpocock`). The `in-progress/` and `deprecated/` upstream sets were not imported. Guaranteed-discovery coverage added in `tests/test_markdown_skills.py`.
- Shared `ExecutionCoordinator` with typed requests/outcomes, material-action approval digests, audit fail-closed preflight, stable error categories, redacted structured logging, audit events, and execution feedback.
- Governance regression coverage for scope, approval, dependency blocking, timeout, cancellation, redaction, and audit-service failure.
- Typed target-requirement metadata and regression coverage for missing-target fail-closed behavior.
- Table-driven governance coverage for every shipped domain CLI command and exact-action skill/capability execution guards.
- Provider-bound execution context and regression coverage for every shipped execution provider.

### Changed

- Mission CLI/workflows, registered conversational skills, the legacy attack chain, and Social IR CLI skill calls now use the shared coordinator.
- Coordinator-backed capability and skill execution denies omitted required targets even when scope is configured as `allow_all`.
- Direct `SkillRegistry` execution is disabled; all execution routes through `ExecutionCoordinator`.
- All shipped domain CLI commands now resolve registered skills through `ExecutionCoordinator`; direct agent, skill, capability-registry, provider, concrete legacy-plugin, nested cross-skill, and raw-shell execution fail closed, and the legacy agent approval callback is removed.
- Provider-based tool discovery now runs through READ coordinator requests, and provider execution must match the request's authorized executor family.
- Network mapper Nmap execution now uses a validated argument vector and structured XML parser instead of invoking another skill.
- Phishing and credential skill adapters now match their current domain APIs; workflow state operations are classified as WRITE.
- Windows CLI output is configured as UTF-8 for every command surface.
- Raw shell compatibility execution is fail-closed and no longer invokes an executor.
- Attack-chain execution uses the session target rather than an internal database target ID.


## v3.0.0 (2026-06-21)

### Added
- **Host Profiler Module** — OS fingerprinting, service discovery, container detection, user enumeration, tool inventory, virtualization detection
- **Network Mapper Module** — Multi-scanner strategy (Masscan/Rustscan/Nmap fallback chain), port range optimization
- **Web Scan Module** — Nuclei JSON-line parser (CVE/CVSS/severity extraction), Nikto vulnerability scanning, WhatWeb tech detection
- **Threat Intel Module** — AbuseIPDB, AlienVault OTX, VirusTotal IP/domain/URL/hash lookup, MISP search+publish, multi-feed aggregation
- **Report Engine Module** — Markdown (TOC, severity cards), HTML (responsive CSS, badges), PDF (weasyprint/wkhtmltopdf) renderers
- **Evidence Core Module** — SHA-256 chain-of-custody with linked hash chain, integrity verification, ZIP/JSON export, retention lifecycle
- **Agent Core Module** — Persistent workflow state machine (JSON), exponential backoff retry, dependency resolution, timeout, cancellation, resume
- **7 Skill wrappers** — Auto-registered via SkillRegistry for all Phase 1 modules
- **SkillCategory enum** — 13 new values (HOST_PROFILING, NETWORK_MAPPING, WEB_SCANNING, EVIDENCE_MANAGEMENT, AGENT_CORE, etc.)

### Changed
- Ruff lint fully clean across 47 test cases
- Phase 1 integration tests all pass (host-profiler, network-mapper, web-scan, evidence-core, agent-core)

## v2.5.0 (2026-06-21)

### Added
- **Phishing Investigator Module** — Email header analysis (SPF/DKIM/DMARC), URL redirect chain analysis, attachment risk scoring (executable/macro/archive detection, YARA placeholder), SMS brand spoofing detection
- **Credential Watch Module** — HIBP API v3 breach lookup, Pwned Passwords k-anonymity hash check, Pastebin public scrape monitoring, deduplicated alert engine with severity scoring
- **Malware Intel Module** — Family mapper (RedLine, Lumma, Vidar, Raccoon, AsyncRAT, Quasar), YARA signature DB, behavior profiling (persistence, evasion, exfiltration, C2, targeted data)
- **Timeline Engine Module** — Event reconstruction with MITRE ATT&CK phase mapping, Mermaid timeline diagrams, ASCII text visualization, structured JSON output
- **Cloud Security Module** — AWS/Azure/GCP provider detection via IMDS, IAM user/role enumeration, S3/Blob/GCS bucket public-access audit
- **AD Enumeration Module** — LDAP user/group/computer/OU queries, domain trust mapping with nltest, SID filtering check, privilege escalation path analysis
- **K8s Audit Module** — Pod security context review (privileged/root/host-network), RBAC wildcard permission detection, secret scanning (Opaque/dockerconfigjson)
- **Attack Graph Module** — Dependency graph building from findings, DFS path analysis (20 paths max), risk scoring, Mermaid + text visualization
- **16 SkillCategory values** — PHISHING_ANALYSIS, CREDENTIAL_MONITORING, MALWARE_INTELLIGENCE, TIMELINE_ANALYSIS, CLOUD_SECURITY, AD_ENUMERATION, K8S_AUDIT, ATTACK_GRAPH
- **16 auto-registered Skill wrappers** — One for each Phase 2-3 module
- **9 CLI subcommand groups** — phishing, credential, malware, timeline, cloud, ad-enum, k8s, attack-graph, agent
- **Expanded REPL finding tracking** — 20 skill categories mapped for automatic evidence collection

### Changed
- At this release, SkillRegistry discovered 29 total skills across 15 active categories
- All 47 existing tests continue to pass
- Ruff lint clean across entire codebase

## v2.0.0 (2026-05-27)

### Added
- **SQLite Persistence Engine** — Session memory with targets, ports, findings, and evidence tables
- **Target Context Tracker** — Auto-links scan results to targets, builds LLM context prompts
- **Evidence Collection System** — Typed evidence (command_output, scan_result, finding) with metadata
- **NmapPro Skill** — Real Nmap execution with XML parsing, service fingerprint extraction, OS detection, NSE script parsing
- **WebTechDetect Skill** — WhatWeb integration with HTTP header fallback, technology fingerprinting
- **DirectoryBruteForce Skill** — Async concurrent directory discovery with path list and gobuster integration
- **Attack Chain Planner** — 6-phase multi-step planner: recon → enumerate → fingerprint → discover → analyze → report
- **Provider-Agnostic LLM Layer** — Swap between Mistral, OpenAI, Anthropic via `--provider` flag
- **Knowledge Graph** — Entity-relationship graph with 12+ seeded nodes (threats, techniques, mitigations, CVEs, tools)
- **Skill Registry** — Recursive subpackage discovery, category/tag/search queries
- **Safety Controller** — Pre-execution permission gate with ALLOW/REQUIRE_APPROVAL/DENY levels
- **Planner** — LLM-driven goal decomposition with workflow step generation
- **Skill Router** — Semantic task-to-skill mapping

### Changed
- Plugin system refactored to Skill framework with typed I/O schemas and categories
- All skills converted to async execution
- CLI updated with session management, attack chain commands, context inspection
- PluginManager now discovers both old-style Plugins and new Skills

### Fixed
- Internal shebang line in setup.py
- Nmap imports made conditional to support environments without python-nmap

## v1.0.0 (2026-05-20)

### Added
- Initial CLI with Rich terminal UI
- Mistral AI integration
- Plugin system with base Plugin class and risk levels
- FAISS vector memory for context retrieval
- Docker sandbox executor
- Initial skills: NetworkScanner, SubdomainEnumerator, WebScanner, DirBruteScanner, ExploitGenerator
- Domain-specific configurations (redteam, malware, cloud)
- Prompt engine with YAML/Jinja2 template system

## v0.1.0 (2026-05-15)

### Added
- Project scaffold and directory structure
- Basic CLI framework
- Research document and architecture specification
- Skill framework concept design
