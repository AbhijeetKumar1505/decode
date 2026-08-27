import json
import re
import uuid
from datetime import datetime
from typing import Any, Dict, Iterator, Optional

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)
_RESPONSE_KEYS = ("message", "action", "command", "decision_summary")


def log_action(action: str, result: str, success: bool = False) -> Dict:
    return {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
        "action": action,
        "result": result,
        "success": success,
    }


def _strip_code_fences(text: str) -> str:
    return _FENCE_RE.sub("", text.strip())


def _try_load(candidate: str) -> Optional[Any]:
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


def parse_llm_response(response: str) -> Dict[str, Any]:
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

    fallback: Optional[Dict[str, Any]] = None
    for candidate in _iter_json_objects(text):
        obj = _try_load(candidate)
        if not isinstance(obj, dict):
            continue
        if any(key in obj for key in _RESPONSE_KEYS):
            return obj
        if fallback is None:
            fallback = obj
    if fallback is not None:
        return fallback

    stripped = response.strip()
    return {
        "decision_summary": "The model reply was not valid JSON; showing its raw text.",
        "message": stripped[:2000] if stripped else "The model returned an empty response.",
        "action": None,
        "params": {},
    }
