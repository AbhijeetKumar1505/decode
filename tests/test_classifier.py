"""Tests for the heuristic prompt task-classifier."""

import unittest

from decode.models import classify_task
from decode.models.classifier import DEFAULT_TASK_CLASS


class ClassifyTaskTest(unittest.TestCase):
    def test_code_intent(self):
        self.assertEqual(
            classify_task("refactor this function and fix the failing pytest"),
            "code",
        )

    def test_planning_intent(self):
        self.assertEqual(
            classify_task("design an architecture and break down the steps"),
            "planning",
        )

    def test_extraction_intent(self):
        self.assertEqual(
            classify_task("extract and summarize the open ports into a table"),
            "extraction",
        )

    def test_analysis_intent(self):
        self.assertEqual(
            classify_task("analyze why the service keeps crashing"),
            "analysis",
        )

    def test_default_when_no_cue(self):
        self.assertEqual(classify_task("hello there"), DEFAULT_TASK_CLASS)
        self.assertEqual(classify_task(""), DEFAULT_TASK_CLASS)

    def test_word_boundary_avoids_false_positive(self):
        # "explanation" must not trigger the planning cue "plan".
        self.assertNotEqual(classify_task("give me an explanation"), "planning")


class GatewayPromptRoutingTest(unittest.TestCase):
    def test_route_for_prompt_feeds_classified_class(self):
        from decode.models import ModelGateway, default_model_registry
        from decode.models.routing import RoutingRequest

        reg = default_model_registry()
        gw = ModelGateway(reg, routing_enabled=True)
        # "implement a function ..." classifies as code; the prompt-routed decision
        # must match routing explicitly for task_class="code".
        by_prompt = gw.route_for_prompt("implement a function to parse the log")
        by_class = gw._router.route(RoutingRequest(task_class="code"))
        self.assertEqual(by_prompt.model_id, by_class.model_id)


if __name__ == "__main__":
    unittest.main()
