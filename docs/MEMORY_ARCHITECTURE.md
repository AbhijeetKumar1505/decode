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
