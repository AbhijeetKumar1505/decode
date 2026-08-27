import json
import unittest

from decode.reports import render, render_sarif, extension_for, FORMATS


def _ctx():
    return {
        "session": {"goal": "scan 10.0.0.5", "target_focus": "10.0.0.5"},
        "targets": [{"ip_address": "10.0.0.5", "ports": [
            {"port": 22, "protocol": "tcp", "service": "ssh", "product": "OpenSSH", "version": "9.0"}
        ]}],
        "findings": [
            {"title": "port_scan on 10.0.0.5", "severity": "high", "category": "recon",
             "technique_id": "T1046", "mitre_tactic": "Discovery", "description": "open ports"},
            {"title": "info note", "severity": "info", "category": "recon"},
        ],
    }


class TestRenderers(unittest.TestCase):
    def test_markdown_contains_findings_and_attack(self):
        md = render(_ctx(), "markdown")
        self.assertIn("port_scan on 10.0.0.5", md)
        self.assertIn("T1046", md)

    def test_json_parses_and_has_findings(self):
        data = json.loads(render(_ctx(), "json"))
        self.assertEqual(len(data["findings"]), 2)
        self.assertEqual(data["session"]["target_focus"], "10.0.0.5")

    def test_sarif_is_valid_2_1_0(self):
        doc = json.loads(render_sarif(_ctx()))
        self.assertEqual(doc["version"], "2.1.0")
        run = doc["runs"][0]
        self.assertEqual(run["tool"]["driver"]["name"], "Decode")
        self.assertEqual(len(run["results"]), 2)
        # high severity -> error level; technique id becomes ruleId
        levels = {r["ruleId"]: r["level"] for r in run["results"]}
        self.assertEqual(levels.get("T1046"), "error")

    def test_html_escapes_and_renders(self):
        ctx = _ctx()
        ctx["findings"][0]["title"] = "<script>alert(1)</script>"
        out = render(ctx, "html")
        self.assertIn("&lt;script&gt;", out)
        self.assertNotIn("<script>alert(1)</script>", out)

    def test_unknown_format_raises(self):
        with self.assertRaises(ValueError):
            render(_ctx(), "pdf")

    def test_extensions(self):
        self.assertEqual(extension_for("markdown"), "md")
        self.assertEqual(extension_for("sarif"), "sarif.json")
        self.assertEqual(set(FORMATS), {"markdown", "json", "sarif", "html"})


if __name__ == "__main__":
    unittest.main()
