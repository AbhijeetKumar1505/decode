# Changelog

## Unreleased

### Removed

- Deleted the orphaned in-tree plugin/tools/planner layer: `decode/tools.py` (`PluginManager`/`ToolRegistry`), the `decode/plugins/` package (manifest, sandbox, lifecycle, and the bundled `recon`/`web`/`network`/`exploit` plugins), the legacy `decode/kernel/planner.py` (`Workflow`/`Planner`), and the test-only `decode/planner/planner.py` (`DAGPlanner`), with their tests. None were on the live agent-loop path. The `PlanGraph`/`PlanNode`/`CompletionCriterion` data types in `decode/planner/dag.py` are retained (used by `HostController`). Skill discovery no longer scans `decode.plugins`.
- Documentation updated to the De-code ten-subsystem plan: extension is via markdown playbooks and native capabilities; an external-integration plugin surface is planned but unbuilt. ADR-004 marked Superseded.
- Removed the dead `build_stdio_client` stub in `decode/execution/mcp.py` (it raised `NotImplementedError` and had no callers). The real MCP client is built by `decode.extensions.mcp_client.build_client`.
- Deleted the leftover empty `decode/plugins/` directory (stale bytecode from the removed plugin layer; no tracked source).

### Changed

- Runtime output trees (`evidence/`, `audit/`, `feedback/`, `logs/`) and volatile `data/` files (session/workflow dumps, history, `bootstrap_report.json`, `tool_registry.json`, SQLite `-shm`/`-wal`) are now git-ignored and untracked; curated `data/evaluations/` and `data/initial_knowledge.json` stay tracked. `.gitkeep` placeholders preserve the runtime directories.
- Declared `mcp` as an optional install extra (`pip install .[mcp]` / `poetry install -E mcp`); the real MCP transport supports `stdio` only (`http`/`sse` fail closed).

### Added

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
