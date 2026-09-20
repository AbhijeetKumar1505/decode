import json
import re
import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Any

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)
_RESPONSE_KEYS = ("message", "tool", "action", "command", "decision_summary")
_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*(?P<tool>[A-Za-z_][\w.-]{0,127})\s*"
    r"(?P<body>.*?)</tool_call>",
    re.DOTALL | re.IGNORECASE,
)
_TOOL_ARG_RE = re.compile(
    r"<arg_key>\s*(?P<key>[A-Za-z_][\w.-]{0,127})\s*</arg_key>\s*"
    r"<arg_value>(?P<value>.*?)</arg_value>",
    re.DOTALL | re.IGNORECASE,
)


def log_action(action: str, result: str, success: bool = False) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
        "action": action,
        "result": result,
        "success": success,
    }


def _strip_code_fences(text: str) -> str:
    return _FENCE_RE.sub("", text.strip())


def _try_load(candidate: str) -> Any | None:
    # strict=False tolerates literal control characters (newlines, tabs) that
    # models often emit unescaped inside string values.
    try:
        return json.loads(candidate, strict=False)
    except (json.JSONDecodeError, ValueError):
        return None


def _iter_json_objects(text: str) -> Iterator[str]:
    """Yield each top-level balanced ``{...}`` substring, respecting strings."""
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for i, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = i
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start != -1:
                yield text[start : i + 1]
                start = -1


def _parse_tool_call_markup(text: str) -> dict[str, Any] | None:
    """Normalize the XML-like tool envelope emitted by some hosted models."""
    calls = list(_TOOL_CALL_RE.finditer(text))
    if not calls:
        return None
    call = calls[0]
    body = call.group("body")
    pairs = list(_TOOL_ARG_RE.finditer(body))
    lowered = body.lower()
    if (
        lowered.count("<arg_key>") != len(pairs)
        or lowered.count("<arg_value>") != len(pairs)
        or _TOOL_ARG_RE.sub("", body).strip()
    ):
        return None
    params: dict[str, Any] = {}
    for pair in pairs:
        key = pair.group("key")
        if key in params:
            return None
        raw_value = pair.group("value").strip()
        try:
            params[key] = json.loads(raw_value, strict=False)
        except (json.JSONDecodeError, ValueError):
            params[key] = raw_value
    decision: dict[str, Any] = {
        "thought": text[: call.start()].strip(),
        "tool": call.group("tool"),
        "params": params,
    }
    if len(calls) > 1:
        decision["additional_tool_calls"] = len(calls) - 1
    return decision


def parse_llm_response(response: str) -> dict[str, Any]:
    """Extract a structured decision object from a model reply.

    Tolerates code fences, prose wrapped around the JSON, multiple objects, and
    unescaped control characters. Prefers the object that looks like a decision
    (has message/action/command). On failure it preserves the raw model text as
    the message so the analysis is never silently lost.
    """
    if not isinstance(response, str):
        response = str(response)
    text = _strip_code_fences(response)

    whole = _try_load(text)
    if isinstance(whole, dict):
        return whole

    fallback: dict[str, Any] | None = None
    for candidate in _iter_json_objects(text):
        obj = _try_load(candidate)
        if not isinstance(obj, dict):
            continue
        if any(key in obj for key in _RESPONSE_KEYS):
            return obj
        if fallback is None:
            fallback = obj
    markup_call = _parse_tool_call_markup(text)
    if markup_call is not None:
        return markup_call
    if fallback is not None:
        return fallback

    stripped = response.strip()
    return {
        "decision_summary": "The model reply was not valid JSON; showing its raw text.",
        "message": stripped[:2000]
        if stripped
        else "The model returned an empty response.",
        "action": None,
        "params": {},
    }
