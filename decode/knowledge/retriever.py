"""KnowledgeRetriever — supplies relevant prior knowledge before/around planning.

Backed by the KnowledgeGraph (keyword index today; the FAISS memory can back a
semantic variant later). On construction it idempotently seeds the graph with
the ATT&CK techniques referenced by the capability map, so a search for
"discovery" or "brute force" surfaces the standard techniques.
"""

from .attack_map import CAPABILITY_ATTACK, AttackTechnique, attack_for_capability
from .graph import KnowledgeGraph, KnowledgeNode


class KnowledgeRetriever:
    def __init__(self, graph: KnowledgeGraph | None = None):
        self._graph = graph or KnowledgeGraph()
        self._seed_attack()

    def _seed_attack(self) -> None:
        existing = set(getattr(self._graph, "_nodes", {}).keys())
        for tech in {t.technique_id: t for t in CAPABILITY_ATTACK.values()}.values():
            node_id = f"attack-{tech.technique_id}"
            if node_id in existing:
                continue
            self._graph.add_node(
                KnowledgeNode(
                    id=node_id,
                    type="technique",
                    name=f"{tech.technique_id} - {tech.name}",
                    description=f"MITRE ATT&CK {tech.tactic} technique {tech.technique_id}",
                    source="MITRE ATT&CK",
                    properties={
                        "tactic": tech.tactic,
                        "technique_id": tech.technique_id,
                    },
                )
            )

    def attack_for_capability(self, capability: str) -> AttackTechnique | None:
        return attack_for_capability(capability)

    def relevant_for_goal(self, goal: str) -> list[dict]:
        return [n.model_dump() for n in self._graph.search(goal)]

    def knowledge_for_capabilities(self, capabilities: list[str]) -> dict[str, dict]:
        """Map each capability to its ATT&CK technique (id/name/tactic)."""
        out: dict[str, dict] = {}
        for cap in capabilities:
            tech = attack_for_capability(cap)
            if tech:
                out[cap] = {
                    "technique_id": tech.technique_id,
                    "name": tech.name,
                    "tactic": tech.tactic,
                }
        return out
