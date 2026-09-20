"""Expand De-code's shorthand capability schemas into valid JSON Schema.

``hostcontrol`` describes tool inputs compactly, e.g. ``{"path": "string",
"glob": "string?"}``. MCP clients validate ``inputSchema`` against the JSON
Schema metaschema, so each property value must itself be a schema object. This
module expands the shorthand to ``{"type": "string"}`` objects and keeps any
parenthetical hint as the property ``description``.

Required fields and ``additionalProperties: false`` are emitted so the schema
shown to models and MCP clients matches the governed runtime contract. Tools
with alternative inputs declare an explicit JSON Schema ``oneOf``.
"""

from __future__ import annotations

from typing import Any

_SCALARS = {
    "string": "string",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
}


def _expand_token(token: str) -> dict[str, Any]:
    """Expand one shorthand token into a JSON Schema property object."""
    description = ""
    if "(" in token:
        head, _, rest = token.partition("(")
        description = rest.rstrip(") ").strip()
        token = head
    token = token.strip()
    if token.endswith("?"):  # optional marker — irrelevant without `required`
        token = token[:-1].strip()

    if token.startswith("enum[") and token.endswith("]"):
        values = [v.strip() for v in token[5:-1].split(",") if v.strip()]
        schema: dict[str, Any] = {"type": "string", "enum": values}
    elif token.endswith("[][]"):
        inner = _SCALARS.get(token[:-4], "string")
        schema = {
            "type": "array",
            "items": {"type": "array", "items": {"type": inner}},
        }
    elif token.endswith("[]"):
        inner = _SCALARS.get(token[:-2], "string")
        schema = {"type": "array", "items": {"type": inner}}
    else:
        schema = {"type": _SCALARS.get(token, "string")}

    if description:
        schema["description"] = description
    return schema


def normalize_input_schema(raw: dict[str, Any]) -> dict[str, Any]:
    """Expand a shorthand input schema into a valid JSON Schema object."""
    properties = raw.get("properties") or {}
    out_props: dict[str, Any] = {}
    required = list(raw.get("required") or [])
    for name, shorthand in properties.items():
        if isinstance(shorthand, dict):
            out_props[name] = shorthand  # already a JSON Schema object
        else:
            token = str(shorthand)
            optional = token.partition("(")[0].strip().endswith("?")
            out_props[name] = _expand_token(token)
            if not optional and name not in required:
                required.append(name)
    normalized = {
        key: value
        for key, value in raw.items()
        if key not in {"properties", "required", "additionalProperties"}
    }
    normalized.update(
        {
            "type": "object",
            "properties": out_props,
            "additionalProperties": bool(raw.get("additionalProperties", False)),
        }
    )
    if required:
        normalized["required"] = required
    return normalized
