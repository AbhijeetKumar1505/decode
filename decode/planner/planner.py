"""DAGPlanner — turns a natural-language goal into a capability DAG.

The planner speaks capabilities, never tools. It ships a deterministic
assessment template (fully testable, no LLM needed) and an optional LLM
decomposition that falls back to the template on any error. Availability of
tools is NOT a planning concern — the planner expresses intent; the executor
and governance layer (F5) decide what is actually runnable/permitted.
"""

import re
from typing import Dict, List, Optional, Tuple

from .dag import CompletionCriterion, PlanGraph, PlanNode, RetryCategory


# (node_id, capability, description, depends_on[])
_NETWORK_TEMPLATE: List[Tuple[str, str, str, List[str]]] = [
    ("discover", "host_discovery", "Discover live hosts", []),
    ("ports", "port_scan", "Enumerate open ports", ["discover"]),
    ("services", "service_detection", "Fingerprint services and versions", ["ports"]),
    ("os", "os_detection", "Detect operating system", ["ports"]),
    ("report", "report", "Compile findings into a report", ["services", "os"]),
]

_WEB_TEMPLATE: List[Tuple[str, str, str, List[str]]] = [
    ("subdomains", "subdomain_enum", "Enumerate subdomains", []),
    ("ports", "port_scan", "Enumerate open ports", []),
    ("services", "service_detection", "Fingerprint services", ["ports"]),
    ("fingerprint", "http_fingerprint", "Identify web technologies", ["services"]),
    ("dirs", "dir_enum", "Enumerate directories/files", ["fingerprint"]),
    ("vulns", "vuln_scan", "Scan for known vulnerabilities", ["fingerprint"]),
    ("report", "report", "Compile findings into a report", ["dirs", "vulns"]),
]

_IP_RE = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?:/\d{1,2})?)\b")
_URL_RE = re.compile(r"\bhttps?://[^\s]+", re.IGNORECASE)
_DOMAIN_RE = re.compile(r"\b([a-z0-9-]+(?:\.[a-z0-9-]+)+)\b", re.IGNORECASE)


class DAGPlanner:
    def __init__(self, provider=None):
        self._provider = provider

    def set_provider(self, provider):
        self._provider = provider

    # ── deterministic planning ─────────────────────────────────────────

    def build(
        self,
        goal: str,
        available_capabilities: Optional[List[str]] = None,
        context: Optional[Dict] = None,
    ) -> PlanGraph:
        template, target = self._select_template(goal)
        graph = PlanGraph(goal=goal, reasoning="Deterministic assessment template")
        params = {"target": target} if target else {}
        allowed = set(available_capabilities) if available_capabilities is not None else None

        included: set = set()
        for node_id, capability, desc, deps in template:
            if allowed is not None and capability not in allowed and capability != "report":
                continue
            included.add(node_id)
            graph.add_node(PlanNode(
                id=node_id,
                capability=capability,
                description=desc,
                params=dict(params),
                depends_on=[d for d in deps if d in included],
            ))
        graph.validate_edges()
        return graph

    def _select_template(self, goal: str):
        url = self._first(_URL_RE, goal)
        if url:
            return _WEB_TEMPLATE, url
        ip = self._first(_IP_RE, goal)
        if ip:
            return _NETWORK_TEMPLATE, ip
        gl = goal.lower()
        if any(k in gl for k in ("web", "http", "site", "application", "app")):
            domain = self._first(_DOMAIN_RE, goal)
            return _WEB_TEMPLATE, domain
        domain = self._first(_DOMAIN_RE, goal)
        if domain:
            return _NETWORK_TEMPLATE, domain
        return _NETWORK_TEMPLATE, None

    @staticmethod
    def _first(pattern, text: str) -> Optional[str]:
        m = pattern.search(text)
        return m.group(0) if m else None

    # ── optional LLM decomposition ─────────────────────────────────────

    async def decompose(
        self,
        goal: str,
        available_capabilities: Optional[List[str]] = None,
        context: Optional[Dict] = None,
    ) -> PlanGraph:
        if not self._provider:
            return self.build(goal, available_capabilities, context)
        caps = ", ".join(available_capabilities or [])
        prompt = _DECOMP_PROMPT.format(goal=goal, capabilities=caps)
        try:
            raw = await self._provider.complete(prompt)
            graph = self._parse(goal, raw)
            graph.validate_edges()
            return graph
        except Exception:
            return self.build(goal, available_capabilities, context)

    def _parse(self, goal: str, raw: str) -> PlanGraph:
        import json

        start, end = raw.find("{"), raw.rfind("}") + 1
        data = json.loads(raw[start:end]) if start >= 0 and end > start else {}
        graph = PlanGraph(goal=goal, reasoning=data.get("reasoning", ""))
        for step in data.get("steps", []):
            graph.add_node(PlanNode(
                id=step["id"],
                capability=step.get("capability", ""),
                description=step.get("description", ""),
                params=step.get("params", {}),
                depends_on=step.get("depends_on", []),
            ))
        return graph


_DECOMP_PROMPT = """You are a security assessment planner. Decompose the goal into a DAG of
capability-typed steps. Use ONLY these capabilities: {capabilities}

Goal: {goal}

Output ONLY valid JSON:
{{
  "reasoning": "brief strategy",
  "steps": [
    {{"id": "s1", "capability": "port_scan", "description": "...", "params": {{"target": "..."}}, "depends_on": []}}
  ]
}}"""
