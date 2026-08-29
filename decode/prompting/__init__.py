"""Prompt composition (subsystem 02).

Assembles the agent-loop system prompt from small, mode-aware fragments instead
of one inline monolith: BASE + MODE + CAPABILITIES + POLICY + TASK-STATE note +
optional PROJECT RULES. Fragments are in-code constants so composition is
deterministic and does not depend on the working directory (unlike the
file/Jinja ``PromptEngine``, which stays for domain/template prompts).
"""

from .composer import PromptComposer, compose_system_prompt

__all__ = ["PromptComposer", "compose_system_prompt"]
