import unittest

from decode.planner import CompletionCriterion, DAGPlanner, PlanGraph, PlanNode


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


class TestDAGPlanner(unittest.TestCase):
    def setUp(self):
        self.planner = DAGPlanner()

    def test_ip_goal_builds_network_plan(self):
        g = self.planner.build("scan 10.0.0.5")
        self.assertIn("ports", g.nodes)
        self.assertEqual(g.nodes["ports"].params.get("target"), "10.0.0.5")
        # port_scan depends on host_discovery in the network template
        self.assertIn("discover", g.nodes["ports"].depends_on)

    def test_url_goal_builds_web_plan(self):
        g = self.planner.build("assess https://example.com/app")
        self.assertIn("fingerprint", g.nodes)
        self.assertIn("vulns", g.nodes)
        self.assertEqual(g.nodes["ports"].params.get("target"), "https://example.com/app")

    def test_available_capabilities_filter(self):
        g = self.planner.build("scan 10.0.0.5", available_capabilities=["host_discovery", "port_scan"])
        self.assertIn("ports", g.nodes)
        self.assertNotIn("services", g.nodes)  # service_detection filtered out
        # report is always retained as the terminal intent
        self.assertIn("report", g.nodes)

    def test_built_graph_is_acyclic(self):
        g = self.planner.build("assess https://example.com")
        # Should not raise
        g.validate_edges()


if __name__ == "__main__":
    unittest.main()
