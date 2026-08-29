import unittest

from decode.planner import PlanGraph, PlanNode


class TestPlanGraph(unittest.TestCase):
    def _graph(self):
        g = PlanGraph(goal="t")
        g.add_node(PlanNode(id="a", capability="host_discovery"))
        g.add_node(PlanNode(id="b", capability="port_scan", depends_on=["a"]))
        g.add_node(PlanNode(id="c", capability="service_detection", depends_on=["b"]))
        return g

    def test_ready_nodes_respects_dependencies(self):
        g = self._graph()
        ready = g.ready_nodes()
        self.assertEqual([n.id for n in ready], ["a"])
        g.mark("a", "success")
        self.assertEqual([n.id for n in g.ready_nodes()], ["b"])

    def test_topological_order(self):
        order = [n.id for n in self._graph().topological_order()]
        self.assertLess(order.index("a"), order.index("b"))
        self.assertLess(order.index("b"), order.index("c"))

    def test_cycle_detected(self):
        g = PlanGraph(goal="t")
        g.add_node(PlanNode(id="a", capability="x", depends_on=["b"]))
        g.add_node(PlanNode(id="b", capability="y", depends_on=["a"]))
        with self.assertRaises(ValueError):
            g.topological_order()

    def test_unknown_dependency_rejected(self):
        g = PlanGraph(goal="t")
        g.add_node(PlanNode(id="a", capability="x", depends_on=["ghost"]))
        with self.assertRaises(ValueError):
            g.validate_edges()

    def test_completion(self):
        g = self._graph()
        self.assertFalse(g.is_complete())
        for nid in ("a", "b", "c"):
            g.mark(nid, "success")
        self.assertTrue(g.is_complete())


if __name__ == "__main__":
    unittest.main()
