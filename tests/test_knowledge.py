import tempfile
import unittest
from pathlib import Path

from decode.knowledge import (
    KnowledgeGraph,
    KnowledgeRetriever,
    attack_for_capability,
    CAPABILITY_ATTACK,
)


class TestAttackMap(unittest.TestCase):
    def test_port_scan_maps_to_discovery(self):
        tech = attack_for_capability("port_scan")
        self.assertEqual(tech.technique_id, "T1046")
        self.assertEqual(tech.tactic, "Discovery")

    def test_unmapped_capability_returns_none(self):
        self.assertIsNone(attack_for_capability("report"))

    def test_attack_map_entries_are_well_formed(self):
        # The capability -> ATT&CK vocabulary is standalone knowledge (no longer
        # tied to a hardcoded capability taxonomy). Every entry must carry a
        # plausible technique id and a non-empty tactic.
        self.assertTrue(CAPABILITY_ATTACK)
        for cap, tech in CAPABILITY_ATTACK.items():
            self.assertTrue(cap, "capability key must be non-empty")
            self.assertRegex(tech.technique_id, r"^T\d{4}(\.\d{3})?$")
            self.assertTrue(tech.tactic, f"{cap} has no tactic")
            self.assertTrue(tech.name, f"{cap} has no technique name")


class TestRetriever(unittest.TestCase):
    def _graph(self):
        # Isolated graph so we don't touch the repo's knowledge_graph.json
        return KnowledgeGraph(path=Path(tempfile.mkdtemp()) / "kg.json")

    def test_seeds_attack_techniques(self):
        retriever = KnowledgeRetriever(self._graph())
        hits = retriever.relevant_for_goal("discovery")
        names = " ".join(h["name"] for h in hits)
        self.assertIn("T1046", names)

    def test_attack_for_capability(self):
        retriever = KnowledgeRetriever(self._graph())
        self.assertEqual(retriever.attack_for_capability("brute_missing"), None)
        self.assertEqual(retriever.attack_for_capability("password_attack").technique_id, "T1110")

    def test_knowledge_for_capabilities(self):
        retriever = KnowledgeRetriever(self._graph())
        mapping = retriever.knowledge_for_capabilities(["port_scan", "report"])
        self.assertIn("port_scan", mapping)
        self.assertNotIn("report", mapping)  # report has no ATT&CK technique
        self.assertEqual(mapping["port_scan"]["tactic"], "Discovery")

    def test_seeding_is_idempotent(self):
        g = self._graph()
        KnowledgeRetriever(g)
        n1 = g.get_statistics()["total_nodes"]
        KnowledgeRetriever(g)  # second pass should not duplicate
        n2 = g.get_statistics()["total_nodes"]
        self.assertEqual(n1, n2)


if __name__ == "__main__":
    unittest.main()
