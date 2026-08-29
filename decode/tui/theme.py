"""Visual design system for the Decode TUI.

One place for the palette, the ``rich`` theme, and the small render helpers the
REPL uses so the interface reads as a single coherent system: user-message
bands, ♦ step bullets, dim "thought" lines, orange file paths, and
syntax-highlighted code blocks with a green "added" band.
"""

from __future__ import annotations

from pathlib import Path

from rich import box
from rich.panel import Panel
from rich.syntax import Syntax
from rich.theme import Theme

# ── palette ──────────────────────────────────────────────────────────────
# Kept small and named by role (not by colour) so the whole UI can be
# re-tinted from here without touching call sites.
DECODE_THEME = Theme(
    {
        "header": "bold grey70",       # top path bar
        "meta": "bold cyan",           # token / model counters
        "user": "bold white",          # user-message band
        "time": "grey50",              # right-aligned timestamps
        "thought": "italic grey58",    # "› Thought for Xs" + running commentary
        "step": "bold cyan",           # ♦ bullet glyph
        "run": "bold green",           # step verb ("Run", "Creating", "Listing")
        "path": "orange1 underline",   # file paths
        "ok": "bold green",
        "fail": "bold red",
        "accent": "cyan",
        "add": "on #07240a",           # green "added" band background
    }
)

# Dark-green background behind created/added code, matching the screenshot's band.
CODE_BG = "#07240a"

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

_EXT_LANG = {
    ".py": "python", ".pyw": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "tsx", ".jsx": "jsx",
    ".sh": "bash", ".bash": "bash", ".zsh": "bash",
    ".json": "json", ".md": "markdown", ".rst": "rst",
    ".html": "html", ".htm": "html", ".css": "css", ".scss": "scss",
    ".yml": "yaml", ".yaml": "yaml", ".toml": "toml", ".ini": "ini", ".cfg": "ini",
    ".go": "go", ".rs": "rust", ".rb": "ruby", ".php": "php",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp",
    ".java": "java", ".kt": "kotlin", ".swift": "swift",
    ".sql": "sql", ".xml": "xml", ".dockerfile": "docker", ".env": "bash",
}


def lang_for(path: str) -> str:
    """Best-effort Pygments lexer name from a file path's extension."""
    name = Path(str(path)).name.lower()
    if name in ("dockerfile", "makefile"):
        return "docker" if name == "dockerfile" else "make"
    return _EXT_LANG.get(Path(name).suffix, "text")


def fmt_path(path: str) -> str:
    """Markup for a file path in the shared 'path' style (orange, underlined)."""
    return f"[path]{path}[/path]"


def diamond(label: str, verb: str = "") -> str:
    """A ♦ step-bullet line: ``♦ <verb> <label>`` with the shared styles."""
    verb_md = f"[run]{verb}[/run] " if verb else ""
    return f"[step]♦[/step] {verb_md}{label}"


def code_panel(
    path: str,
    code: str,
    lang: str | None = None,
    *,
    max_lines: int = 60,
) -> Panel:
    """A syntax-highlighted code block with line numbers on a green add-band.

    Long content is clipped to ``max_lines`` so a big file never floods the
    transcript; the clip is signalled with a trailing marker line.
    """
    lines = code.splitlines()
    clipped = len(lines) > max_lines
    body = "\n".join(lines[:max_lines])
    if clipped:
        body += f"\n… (+{len(lines) - max_lines} more lines)"
    syntax = Syntax(
        body,
        lang or lang_for(path),
        line_numbers=True,
        theme="monokai",
        background_color=CODE_BG,
        word_wrap=False,
    )
    return Panel(syntax, border_style="green", box=box.MINIMAL, padding=(0, 1))
