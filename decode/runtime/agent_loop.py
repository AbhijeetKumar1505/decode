"""Bounded tool-use loop over the unified host + security capability surface.

The model is shown the available tools (host operations and security
capabilities) and drives a plan → call tool → observe → iterate loop. Every tool
call is executed through the caller-supplied ``invoke`` coroutine, which routes
to the governed coordinator — the loop itself never touches a host or a socket.
The loop is bounded by a step budget and stops when the model returns a final
message instead of a tool call.
"""

from __future__ import annotations

import inspect
import json
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ..prompting import compose_system_prompt
from ..schema import TaskMode
from ..utils import parse_llm_response

# invoke(name, params) -> observation dict (should include "success" and "summary")
InvokeTool = Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]
# on_step(event) -> None; event["phase"] is "call" | "result" | "final".
StepCallback = Callable[[Dict[str, Any]], None]


class ToolUseLoop:
    def __init__(
        self,
        provider: Any,
        tools: List[Dict[str, Any]],
        invoke: InvokeTool,
        max_steps: int = 8,
        on_step: Optional[StepCallback] = None,
        task_state: Any = None,
        mode: TaskMode = TaskMode.HYBRID,
        project_rules: str = "",
        verifier: Any = None,
        max_replans: int = 2,
    ) -> None:
        self._provider = provider
        self._tools = tools
        self._invoke = invoke
        self._max_steps = max(1, max_steps)
        self._tool_names = {t["name"] for t in tools}
        self._on_step = on_step
        self._mode = mode
        self._project_rules = project_rules
        # Verification (subsystem 10): before accepting a "done" message, check the
        # task's completion conditions; on failure, replan (bounded) rather than
        # reporting false success. Inert unless completion conditions are declared.
        self._verifier = verifier
        self._max_replans = max(0, max_replans)
        self._replans = 0
        # Optional live task-state (Neural Schema, subsystem 04). When present the
        # loop renders a compact view of it into the prompt each turn and records
        # every action/observation into it, so reasoning is not driven by the raw
        # message log alone.
        self._task_state = task_state

    def _emit(self, event: Dict[str, Any]) -> None:
        if self._on_step is None:
            return
        try:
            self._on_step(event)
        except Exception:  # a broken UI callback must never break the loop
            pass

    def _system_prompt(self) -> str:
        mode = self._task_state.mode if self._task_state is not None else self._mode
        return compose_system_prompt(mode, self._tools, project_rules=self._project_rules)

    async def run(self, goal: str) -> Dict[str, Any]:
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": f"Goal: {goal}"},
        ]
        steps: List[Dict[str, Any]] = []
        last_observation: Optional[Dict[str, Any]] = None
        for _ in range(self._max_steps):
            # Inject a compact, refreshed view of the task state for this turn only,
            # then drop it so the transient context never accumulates in history.
            state_message = self._state_message()
            if state_message is not None:
                messages.append(state_message)
            start = time.monotonic()
            tokens_before = getattr(self._provider, "session_tokens", 0)
            raw = await self._provider.chat(messages)
            elapsed = time.monotonic() - start
            step_tokens = getattr(self._provider, "session_tokens", 0) - tokens_before
            if state_message is not None:
                messages.remove(state_message)
            decision = parse_llm_response(raw)
            thought = str(decision.get("thought") or decision.get("reasoning") or "").strip()
            tool = decision.get("tool")
            if not tool:
                # Verify before accepting completion; replan (bounded) on failure.
                if self._task_state is not None and self._verifier is not None:
                    verdict = self._verifier.verify(self._task_state, last_observation)
                    if inspect.isawaitable(verdict):  # e.g. a reviewer-model verifier
                        verdict = await verdict
                    if not verdict.valid and self._replans < self._max_replans:
                        self._replans += 1
                        self._task_state.mark("investigating")
                        self._emit({"phase": "verify", "valid": False,
                                    "failed": verdict.failed_criteria, "replans": self._replans})
                        messages.append({"role": "assistant", "content": raw})
                        messages.append({
                            "role": "user",
                            "content": (
                                "Verification failed before completing: "
                                + "; ".join(verdict.failed_criteria)
                                + ". Continue working to satisfy the completion conditions, "
                                "or explain in a final message why they cannot be met."
                            ),
                        })
                        continue
                if self._task_state is not None:
                    self._task_state.mark("complete")
                self._emit({"phase": "final", "thought": thought, "message": decision.get("message", ""),
                            "elapsed": elapsed, "tokens": step_tokens, "state_summary": self._state_summary()})
                return {"final": decision.get("message", ""), "thought": thought, "steps": steps,
                        "stopped": "final", "state_summary": self._state_summary()}
            params = decision.get("params") or {}
            if self._task_state is not None:
                self._task_state.record_action(tool, params, thought)
            self._emit({"phase": "call", "thought": thought, "tool": tool, "params": params,
                        "elapsed": elapsed, "tokens": step_tokens})
            if tool not in self._tool_names:
                observation = {"success": False, "summary": f"unknown tool '{tool}'"}
            else:
                observation = await self._invoke(tool, params)
            last_observation = observation
            if self._task_state is not None:
                self._task_state.record_observation(tool, observation)
            self._emit({"phase": "result", "tool": tool, "observation": observation})
            steps.append({"tool": tool, "params": params, "thought": thought, "observation": observation})
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": f"Observation from {tool}: {json.dumps(observation, default=str)[:1500]}",
            })
        return {"final": "step budget exhausted", "steps": steps, "stopped": "budget",
                "state_summary": self._state_summary()}

    def _state_message(self) -> Optional[Dict[str, str]]:
        if self._task_state is None:
            return None
        return {"role": "system", "content": "Current task state:\n" + self._task_state.render_compact()}

    def _state_summary(self) -> str:
        return self._task_state.render_compact() if self._task_state is not None else ""
