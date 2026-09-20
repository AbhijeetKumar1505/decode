# Memory Engine Implementation Note

**Status:** Migration note; see [MEMORY_ARCHITECTURE.md](MEMORY_ARCHITECTURE.md)

Current `src/decode/memory/` and `knowledge/` provide layered memory,
project knowledge, retrieval, and learning foundations. They remain usable but
are not authority over state, policy, evidence, or workflow.

Migration: inventory shapes/isolation; add provenance/classification/freshness;
separate working/task/project/repository APIs; bind writes to events/evidence;
test conflicts/poisoning/retention/export/deletion; version storage migrations;
put retrieval selection/cost under UTOS.

A retrieved record is an observation with provenance—not an instruction,
approval, confirmed finding, or permission.
