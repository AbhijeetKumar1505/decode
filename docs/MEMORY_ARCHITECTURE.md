# Memory Architecture

**Status:** Current memory/knowledge modules are foundations; four layers Target

Do not store conversation as memory. Store structured provenance-linked state.

| Layer | Lifetime | Content |
|---|---|---|
| Working | node/phase | selected context, observations, hypotheses |
| Task | task/run | decisions, nodes, failures, evidence, tests |
| Project | across tasks | architecture, conventions, boundaries, issues |
| Repository | file/version | symbols, imports, dependencies, hashes |

Graphs may represent assets, services, techniques, findings, mitigations, and
evidence, retaining confidence/provenance.

Only validated observations/decisions persist. Record project, source, event/
evidence, producer, confidence, freshness, classification, schema. Summaries are
derived and cannot overwrite facts.

Retrieval is project/scope/classification/freshness aware and UTOS-bounded.
Retrieved content is untrusted context. Conflicts remain explicit.

Order: exact/current state; symbol/dependency; graph; lexical; optional semantic.
Embeddings are optional.

Compression creates linked derived records and cannot silently discard evidence
or unresolved risk. Retention/export/deletion/hold are audited.

Defend poisoning with provenance, trust, isolation, contradiction detection,
freshness, write authorization, and adversarial tests. Web/tool/model content is
not trusted guidance automatically.

Current `memory/`, `knowledge/`, TaskState, evidence, and persistence are
foundations to consolidate incrementally.

## Engineering knowledge layer — Target

Separate event memory (what happened), verified knowledge (what is supported),
and reasoning (what to do next). Core and Active Brain consume scoped retrieval;
UTOS budgets that retrieval but does not own knowledge or grant authority.

Build on the existing project-scoped SQLite node/edge store first. Add stable
identities, typed relationships, provenance/evidence references, lifecycle state,
classification, freshness, and bounded traversal. Exact state and repository
symbols precede graph and lexical search; SQLite FTS5 is an optional local
index. Embeddings and a separate graph engine require a measured benefit over
this baseline and remain Research, not current dependencies.

An Obsidian-compatible Markdown vault is an optional, initially read-only
interface for human-authored notes. Markdown is source for those notes only;
SQLite task state, approvals, audit, findings, and protected raw evidence remain
authoritative in their own stores. Vault import must enforce explicit path and
project scope, reject symlink/path escapes, classify sensitive content, and
treat links and note instructions as untrusted data. Existing personal vaults
are never discovered, edited, or synchronized without explicit authorization.

Agent observations may propose notes or relationships, but cannot directly
promote hypotheses to verified facts. Promotion requires validation evidence,
source attribution, conflict review, and an auditable decision. Notes can be
deprecated without deleting their provenance. Two-way sync and model-authored
writes are Deferred pending conflict, rollback, and data-rights design.

Before graph traversal becomes an Active Brain input, validate that both edge
endpoints belong to the declared project; the current SQLite edge writer does
not yet enforce this. The legacy JSON graph is not a project-isolated source of
authority.
