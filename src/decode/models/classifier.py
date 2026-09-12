"""Heuristic prompt task-classifier → routing ``task_class``.

Infers a coarse task class from a natural-language goal so routing
(:class:`RoutingRequest.task_class`) can be automatic instead of role-only. It is
deliberately a lightweight, deterministic keyword heuristic — no model call — so
it is fast, testable, and free. The classes match the registry's
``quality_scores`` keys.
"""

from __future__ import annotations

import re

TASK_CLASSES = ("code", "planning", "analysis", "extraction")
DEFAULT_TASK_CLASS = "analysis"

# Keyword cues per class. Matched on word boundaries so "plan" doesn't fire on
# "explanation". Ordered by tie-break priority below.
_CUES: dict[str, tuple[str, ...]] = {
    "code": (
        "code",
        "coding",
        "function",
        "class",
        "method",
        "refactor",
        "implement",
        "debug",
        "bug",
        "fix",
        "patch",
        "compile",
        "traceback",
        "exception",
        "unit test",
        "pytest",
        "lint",
        "stack trace",
        "regex",
        "endpoint",
        "api",
        "build",
        "dependency",
        "syntax",
        "variable",
        "script",
    ),
    "planning": (
        "plan",
        "design",
        "architect",
        "architecture",
        "strategy",
        "approach",
        "roadmap",
        "outline",
        "break down",
        "prioritize",
        "steps",
        "milestones",
        "propose",
        "blueprint",
    ),
    "extraction": (
        "extract",
        "parse",
        "enumerate",
        "list all",
        "summarize",
        "summary",
        "pull out",
        "fields",
        "csv",
        "table of",
        "scrape",
        "collect the",
    ),
    "analysis": (
        "analyze",
        "analyse",
        "assess",
        "investigate",
        "evaluate",
        "review",
        "explain",
        "why",
        "diagnose",
        "compare",
        "audit",
        "understand",
    ),
}

# Tie-break priority (most specific intent first).
_PRIORITY = ("code", "planning", "extraction", "analysis")

_COMPILED: dict[str, list[re.Pattern[str]]] = {
    task_class: [
        re.compile(rf"(?<!\w){re.escape(cue)}(?!\w)", re.IGNORECASE) for cue in cues
    ]
    for task_class, cues in _CUES.items()
}


def classify_task(prompt: str) -> str:
    """Infer a routing ``task_class`` from a prompt (default ``analysis``)."""
    text = prompt or ""
    scores = {
        task_class: sum(1 for pat in patterns if pat.search(text))
        for task_class, patterns in _COMPILED.items()
    }
    best = max(scores.values())
    if best == 0:
        return DEFAULT_TASK_CLASS
    # Highest score wins; ties resolved by the specificity priority order.
    return min(
        (tc for tc, score in scores.items() if score == best),
        key=_PRIORITY.index,
    )
