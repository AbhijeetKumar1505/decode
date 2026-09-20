import unittest

from decode.utils import parse_llm_response

INVALID = "The model returned an invalid structured response."


class TestParseLLMResponse(unittest.TestCase):
    def test_plain_object(self):
        self.assertEqual(
            parse_llm_response('{"message": "hi", "action": null}')["message"], "hi"
        )

    def test_prose_before_json(self):
        out = parse_llm_response('Analysis follows.\n{"message": "ok", "action": null}')
        self.assertEqual(out["message"], "ok")

    def test_code_fenced_json(self):
        out = parse_llm_response('```json\n{"message": "fenced", "action": null}\n```')
        self.assertEqual(out["message"], "fenced")

    def test_json_then_trailing_prose_with_brace(self):
        # The exact host_profiler failure: valid JSON, then commentary with a brace.
        out = parse_llm_response(
            '{"message": "profiled", "action": null}\nNote: services {truncated}'
        )
        self.assertEqual(out["message"], "profiled")

    def test_multiple_objects_prefers_decision_shaped(self):
        out = parse_llm_response(
            '{"a": 1}\nand then\n{"message": "second", "action": null}'
        )
        self.assertEqual(out["message"], "second")

    def test_unescaped_newlines_in_value(self):
        out = parse_llm_response('{"message": "line1\nline2", "action": null}')
        self.assertEqual(out["message"], "line1\nline2")

    def test_xml_style_tool_call_is_normalized(self):
        out = parse_llm_response(
            "I'll inspect the directory.\n"
            "<tool_call>file_list\n"
            "<arg_key>path</arg_key>\n"
            "<arg_value>/mnt/e/hackagent</arg_value>\n"
            "</tool_call>"
        )
        self.assertEqual(out["thought"], "I'll inspect the directory.")
        self.assertEqual(out["tool"], "file_list")
        self.assertEqual(out["params"], {"path": "/mnt/e/hackagent"})

    def test_multiple_xml_tool_calls_execute_only_the_first(self):
        out = parse_llm_response(
            "<tool_call>file_list"
            "<arg_key>path</arg_key><arg_value>.</arg_value>"
            "</tool_call>"
            "<tool_call>list_tools</tool_call>"
        )
        self.assertEqual(out["tool"], "file_list")
        self.assertEqual(out["params"], {"path": "."})
        self.assertEqual(out["additional_tool_calls"], 1)

    def test_xml_tool_arguments_retain_json_types(self):
        out = parse_llm_response(
            "<tool_call>process_wait"
            "<arg_key>pid</arg_key><arg_value>42</arg_value>"
            "<arg_key>terminate</arg_key><arg_value>true</arg_value>"
            "</tool_call>"
        )
        self.assertEqual(out["params"], {"pid": 42, "terminate": True})

    def test_malformed_or_duplicate_xml_arguments_are_not_executed(self):
        malformed = parse_llm_response(
            "<tool_call>file_list<arg_key>path</arg_key></tool_call>"
        )
        duplicate = parse_llm_response(
            "<tool_call>file_list"
            "<arg_key>path</arg_key><arg_value>.</arg_value>"
            "<arg_key>path</arg_key><arg_value>/tmp</arg_value>"
            "</tool_call>"
        )
        self.assertIsNone(malformed["action"])
        self.assertIsNone(duplicate["action"])

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
