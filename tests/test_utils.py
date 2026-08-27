import unittest

from decode.utils import parse_llm_response

INVALID = "The model returned an invalid structured response."


class TestParseLLMResponse(unittest.TestCase):
    def test_plain_object(self):
        self.assertEqual(parse_llm_response('{"message": "hi", "action": null}')["message"], "hi")

    def test_prose_before_json(self):
        out = parse_llm_response('Analysis follows.\n{"message": "ok", "action": null}')
        self.assertEqual(out["message"], "ok")

    def test_code_fenced_json(self):
        out = parse_llm_response('```json\n{"message": "fenced", "action": null}\n```')
        self.assertEqual(out["message"], "fenced")

    def test_json_then_trailing_prose_with_brace(self):
        # The exact host_profiler failure: valid JSON, then commentary with a brace.
        out = parse_llm_response('{"message": "profiled", "action": null}\nNote: services {truncated}')
        self.assertEqual(out["message"], "profiled")

    def test_multiple_objects_prefers_decision_shaped(self):
        out = parse_llm_response('{"a": 1}\nand then\n{"message": "second", "action": null}')
        self.assertEqual(out["message"], "second")

    def test_unescaped_newlines_in_value(self):
        out = parse_llm_response('{"message": "line1\nline2", "action": null}')
        self.assertEqual(out["message"], "line1\nline2")

    def test_non_json_preserves_raw_text(self):
        out = parse_llm_response("The host is Kali on WSL2 with kernel 6.18.")
        self.assertNotIn("message", {INVALID})  # sanity
        self.assertIn("Kali on WSL2", out["message"])
        self.assertIsNone(out["action"])

    def test_empty_response(self):
        out = parse_llm_response("")
        self.assertIn("empty", out["message"].lower())

    def test_non_string_input(self):
        out = parse_llm_response({"message": "already a dict"})  # type: ignore[arg-type]
        self.assertIn("already a dict", out["message"])


if __name__ == "__main__":
    unittest.main()
