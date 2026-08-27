from typing import Dict, Any, List, Optional
from .store import SessionStore


class TargetFinding:
    def __init__(
        self,
        title: str,
        description: str,
        severity: str = "medium",
        category: str = "",
        cve_id: str = "",
        technique_id: str = "",
        mitre_tactic: str = "",
        confidence: str = "medium",
    ):
        self.title = title
        self.description = description
        self.severity = severity
        self.category = category
        self.cve_id = cve_id
        self.technique_id = technique_id
        self.mitre_tactic = mitre_tactic
        self.confidence = confidence
        self.evidence_refs: List[str] = []


class TargetContextTracker:
    def __init__(self, store: SessionStore, session_id: Optional[str] = None):
        self._store = store
        self._current_session_id: Optional[str] = session_id
        self._current_target_id: Optional[str] = None

    def start_session(self, goal: str = "", target_focus: str = ""):
        self._current_session_id = self._store.create_session(
            goal=goal, target_focus=target_focus
        )
        return self._current_session_id

    def resume_session(self, session_id: str):
        self._current_session_id = session_id

    @property
    def session_id(self) -> Optional[str]:
        return self._current_session_id

    @property
    def store(self) -> SessionStore:
        return self._store

    def track_target(
        self,
        hostname: str = "",
        ip: str = "",
        domain: str = "",
        os: str = "",
        metadata: Optional[Dict] = None,
    ) -> str:
        if not self._current_session_id:
            raise RuntimeError("No active session. Call start_session() first.")
        self._current_target_id = self._store.upsert_target(
            self._current_session_id,
            hostname=hostname,
            ip=ip,
            domain=domain,
            os=os,
            metadata=metadata,
        )
        return self._current_target_id

    @property
    def target_id(self) -> Optional[str]:
        return self._current_target_id

    def record_port(
        self,
        port: int,
        protocol: str = "tcp",
        state: str = "open",
        service: str = "",
        product: str = "",
        version: str = "",
        extra: str = "",
    ):
        if not self._current_target_id:
            raise RuntimeError("No current target. Call track_target() first.")
        self._store.upsert_port(
            self._current_target_id,
            port,
            protocol,
            state,
            service,
            product,
            version,
            extra,
        )

    def record_finding(self, finding: TargetFinding) -> str:
        if not self._current_session_id:
            raise RuntimeError("No active session.")
        return self._store.add_finding(
            session_id=self._current_session_id,
            title=finding.title,
            description=finding.description,
            severity=finding.severity,
            category=finding.category,
            cve_id=finding.cve_id,
            technique_id=finding.technique_id,
            mitre_tactic=finding.mitre_tactic,
            confidence=finding.confidence,
            target_id=self._current_target_id,
        )

    def record_evidence(
        self,
        type: str,
        label: str,
        data: Dict[str, Any],
        source: str = "",
        finding_id: Optional[str] = None,
    ) -> str:
        if not self._current_session_id:
            raise RuntimeError("No active session.")
        return self._store.add_evidence(
            session_id=self._current_session_id,
            type=type,
            label=label,
            data=data,
            source=source,
            finding_id=finding_id,
        )

    def build_context_prompt(self) -> str:
        if not self._current_session_id:
            return "No active session."
        ctx = self._store.get_session_context(self._current_session_id)
        lines = [f"Session: {ctx['session']['goal']}"]
        for t in ctx["targets"]:
            host = t.get("hostname") or t.get("ip_address") or "unknown"
            lines.append(f"  Target: {host}")
            for p in t.get("ports", []):
                svc = p.get("service", "unknown")
                prod = p.get("product", "")
                ver = p.get("version", "")
                prod_str = f" ({prod} {ver})" if prod else ""
                lines.append(f"    Port {p['port']}/{p['protocol']}: {svc}{prod_str}")
        findings = ctx.get("findings", [])
        if findings:
            lines.append(f"  Findings ({len(findings)}):")
            for f in findings:
                lines.append(f"    [{f['severity'].upper()}] {f['title']}")
        return "\n".join(lines)

    def get_open_ports_summary(self) -> List[Dict[str, Any]]:
        if not self._current_session_id:
            return []
        ctx = self._store.get_session_context(self._current_session_id)
        ports = []
        for t in ctx.get("targets", []):
            for p in t.get("ports", []):
                ports.append(
                    {
                        "target": t.get("hostname") or t.get("ip_address", ""),
                        "port": p["port"],
                        "protocol": p["protocol"],
                        "service": p["service"],
                        "product": p["product"],
                        "version": p["version"],
                    }
                )
        return ports
