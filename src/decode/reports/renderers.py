"""Report renderers over a SessionStore session context.

A ``ctx`` is the dict returned by SessionStore.get_session_context():
``{session, targets, findings, evidence}``. Findings may carry
``technique_id`` / ``mitre_tactic`` (populated by the knowledge layer), which
the SARIF renderer surfaces as rule ids / properties.
"""

import html
import json
from datetime import UTC, datetime

FORMATS = ("markdown", "json", "sarif", "html")

# finding severity -> SARIF level
_SARIF_LEVEL = {
    "critical": "error",
    "high": "error",
    "medium": "warning",
    "low": "note",
    "info": "note",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def render_markdown(ctx: dict) -> str:
    session = ctx.get("session", {})
    targets = ctx.get("targets", [])
    findings = ctx.get("findings", [])
    lines = [
        "# Assessment Report",
        "",
        f"- **Goal:** {session.get('goal', 'N/A')}",
        f"- **Target focus:** {session.get('target_focus', 'N/A')}",
        f"- **Generated:** {_now()}",
        "",
        f"## Targets ({len(targets)})",
    ]
    for t in targets:
        host = t.get("hostname") or t.get("ip_address") or "unknown"
        lines.append(f"- **{host}**")
        for p in t.get("ports", []):
            prod = f" ({p.get('product', '')} {p.get('version', '')})".rstrip()
            lines.append(
                f"  - Port {p['port']}/{p.get('protocol', 'tcp')}: {p.get('service', '')}{prod}"
            )
    lines += ["", f"## Findings ({len(findings)})"]
    if not findings:
        lines.append("_No findings recorded._")
    for f in findings:
        lines.append(
            f"### [{f.get('severity', 'info').upper()}] {f.get('title', 'Finding')}"
        )
        meta = []
        if f.get("category"):
            meta.append(f"Category: {f['category']}")
        if f.get("technique_id"):
            meta.append(f"ATT&CK: {f['technique_id']} ({f.get('mitre_tactic', '')})")
        if meta:
            lines.append(f"- {' | '.join(meta)}")
        if f.get("description"):
            lines.append(f"- {f['description']}")
        lines.append("")
    return "\n".join(lines)


def render_json(ctx: dict) -> str:
    return json.dumps(
        {
            "generated": _now(),
            "session": ctx.get("session", {}),
            "targets": ctx.get("targets", []),
            "findings": ctx.get("findings", []),
        },
        indent=2,
    )


def render_sarif(ctx: dict) -> str:
    findings = ctx.get("findings", [])
    rules, results = {}, []
    for f in findings:
        rule_id = f.get("technique_id") or f.get("category") or "finding"
        rules.setdefault(
            rule_id,
            {
                "id": rule_id,
                "name": f.get("mitre_tactic") or f.get("category") or "Finding",
            },
        )
        results.append(
            {
                "ruleId": rule_id,
                "level": _SARIF_LEVEL.get(f.get("severity", "info"), "note"),
                "message": {
                    "text": f.get("title", "")
                    + (f" — {f['description']}" if f.get("description") else "")
                },
                "properties": {
                    "severity": f.get("severity", "info"),
                    "tactic": f.get("mitre_tactic", ""),
                    "category": f.get("category", ""),
                },
            }
        )
    doc = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Decode",
                        "informationUri": "https://github.com/decode",
                        "rules": list(rules.values()),
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(doc, indent=2)


def render_html(ctx: dict) -> str:
    session = ctx.get("session", {})
    findings = ctx.get("findings", [])
    rows = ""
    for f in findings:
        rows += (
            "<tr>"
            f"<td>{html.escape(str(f.get('severity', '')))}</td>"
            f"<td>{html.escape(str(f.get('title', '')))}</td>"
            f"<td>{html.escape(str(f.get('technique_id', '')))} {html.escape(str(f.get('mitre_tactic', '')))}</td>"
            f"<td>{html.escape(str(f.get('description', '')))}</td>"
            "</tr>"
        )
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Decode Report</title>"
        "<style>body{font-family:sans-serif;margin:2rem}table{border-collapse:collapse;width:100%}"
        "th,td{border:1px solid #ccc;padding:.4rem;text-align:left}</style></head><body>"
        f"<h1>Assessment Report</h1><p><b>Goal:</b> {html.escape(str(session.get('goal', 'N/A')))}<br>"
        f"<b>Generated:</b> {_now()}</p>"
        f"<h2>Findings ({len(findings)})</h2>"
        "<table><tr><th>Severity</th><th>Title</th><th>ATT&CK</th><th>Description</th></tr>"
        f"{rows}</table></body></html>"
    )


_RENDERERS = {
    "markdown": render_markdown,
    "json": render_json,
    "sarif": render_sarif,
    "html": render_html,
}

_EXTENSIONS = {"markdown": "md", "json": "json", "sarif": "sarif.json", "html": "html"}


def render(ctx: dict, fmt: str) -> str:
    if fmt not in _RENDERERS:
        raise ValueError(f"unknown report format: {fmt}. Available: {list(_RENDERERS)}")
    return _RENDERERS[fmt](ctx)


def extension_for(fmt: str) -> str:
    return _EXTENSIONS.get(fmt, "txt")
