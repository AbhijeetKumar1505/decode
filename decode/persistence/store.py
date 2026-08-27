import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

from .evidence import ProtectedEvidenceStore


class SessionStore:
    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or Path("data/decode.db")
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._evidence_store = ProtectedEvidenceStore(
            self._db_path.parent / "evidence"
        )
        self._conn: Optional[sqlite3.Connection] = None
        self._connect()
        self._init_schema()

    def _connect(self):
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    def _init_schema(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                goal TEXT NOT NULL DEFAULT '',
                target_focus TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS targets (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                hostname TEXT DEFAULT '',
                ip_address TEXT DEFAULT '',
                domain TEXT DEFAULT '',
                os TEXT DEFAULT '',
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                metadata TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS ports (
                id TEXT PRIMARY KEY,
                target_id TEXT NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
                port INTEGER NOT NULL,
                protocol TEXT DEFAULT 'tcp',
                state TEXT DEFAULT 'unknown',
                service TEXT DEFAULT '',
                product TEXT DEFAULT '',
                version TEXT DEFAULT '',
                extra_info TEXT DEFAULT '',
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS findings (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                target_id TEXT REFERENCES targets(id) ON DELETE SET NULL,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                severity TEXT DEFAULT 'medium',
                category TEXT DEFAULT '',
                cve_id TEXT DEFAULT '',
                technique_id TEXT DEFAULT '',
                mitre_tactic TEXT DEFAULT '',
                confidence TEXT DEFAULT 'medium',
                evidence_ids TEXT DEFAULT '[]',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS evidence (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                finding_id TEXT REFERENCES findings(id) ON DELETE SET NULL,
                type TEXT NOT NULL DEFAULT 'command_output',
                label TEXT DEFAULT '',
                data TEXT NOT NULL DEFAULT '{}',
                source TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                scope TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
                session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
                type TEXT NOT NULL DEFAULT 'host',
                key TEXT NOT NULL DEFAULT '',
                value TEXT DEFAULT '',
                sensitive INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS missions (
                session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
                plan_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS mission_nodes (
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                node_id TEXT NOT NULL,
                material_fingerprint TEXT NOT NULL,
                idempotency_key TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                result_summary TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (session_id, node_id)
            );

            CREATE TABLE IF NOT EXISTS project_knowledge_nodes (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                type TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                provenance TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS project_knowledge_edges (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                source_id TEXT NOT NULL REFERENCES project_knowledge_nodes(id) ON DELETE CASCADE,
                target_id TEXT NOT NULL REFERENCES project_knowledge_nodes(id) ON DELETE CASCADE,
                relationship TEXT NOT NULL,
                provenance TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memory_events (
                id TEXT PRIMARY KEY,
                project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
                event TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_targets_session ON targets(session_id);
            CREATE INDEX IF NOT EXISTS idx_ports_target ON ports(target_id);
            CREATE INDEX IF NOT EXISTS idx_findings_session ON findings(session_id);
            CREATE INDEX IF NOT EXISTS idx_evidence_session ON evidence(session_id);
            CREATE INDEX IF NOT EXISTS idx_artifacts_project ON artifacts(project_id);
            CREATE INDEX IF NOT EXISTS idx_artifacts_session ON artifacts(session_id);
        """)
        self._conn.commit()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _new_id(self) -> str:
        return str(uuid.uuid4())

    # ── Sessions ──

    def create_session(self, goal: str = "", target_focus: str = "") -> str:
        sid = self._new_id()
        now = self._now()
        self._conn.execute(
            "INSERT INTO sessions (id, goal, target_focus, status, created_at, updated_at) VALUES (?, ?, ?, 'active', ?, ?)",
            (sid, goal, target_focus, now, now),
        )
        self._conn.commit()
        return sid

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_sessions(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def update_session(self, session_id: str, **kwargs):
        allowed = {"goal", "target_focus", "status"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = self._now()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [session_id]
        # safe: column names filtered to allowed set
        self._conn.execute(f"UPDATE sessions SET {set_clause} WHERE id = ?", values)  # nosec B608
        self._conn.commit()

    def close_session(self, session_id: str):
        self.update_session(session_id, status="closed")

    # ── Targets ──

    def upsert_target(
        self,
        session_id: str,
        hostname: str = "",
        ip: str = "",
        domain: str = "",
        os: str = "",
        metadata: Optional[Dict] = None,
    ) -> str:
        existing = self._conn.execute(
            "SELECT * FROM targets WHERE session_id = ? AND (hostname = ? OR ip_address = ?) AND hostname != ''",
            (session_id, hostname, ip),
        ).fetchone()
        now = self._now()
        if existing:
            tid = existing["id"]
            self._conn.execute(
                "UPDATE targets SET last_seen = ?, os = COALESCE(NULLIF(?, ''), os), metadata = ? WHERE id = ?",
                (now, os, json.dumps(metadata or {}), tid),
            )
            self._conn.commit()
            return tid
        tid = self._new_id()
        self._conn.execute(
            "INSERT INTO targets (id, session_id, hostname, ip_address, domain, os, first_seen, last_seen, metadata) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                tid,
                session_id,
                hostname,
                ip,
                domain,
                os,
                now,
                now,
                json.dumps(metadata or {}),
            ),
        )
        self._conn.commit()
        return tid

    def get_target(self, target_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM targets WHERE id = ?", (target_id,)
        ).fetchone()
        if row:
            d = dict(row)
            d["metadata"] = json.loads(d.get("metadata", "{}"))
            return d
        return None

    def get_targets(self, session_id: str) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM targets WHERE session_id = ? ORDER BY last_seen DESC",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Ports ──

    def upsert_port(
        self,
        target_id: str,
        port: int,
        protocol: str = "tcp",
        state: str = "open",
        service: str = "",
        product: str = "",
        version: str = "",
        extra: str = "",
    ) -> str:
        existing = self._conn.execute(
            "SELECT * FROM ports WHERE target_id = ? AND port = ? AND protocol = ?",
            (target_id, port, protocol),
        ).fetchone()
        now = self._now()
        if existing:
            pid = existing["id"]
            self._conn.execute(
                "UPDATE ports SET state = ?, service = ?, product = ?, version = ?, extra_info = ?, last_seen = ? WHERE id = ?",
                (state, service, product, version, extra, now, pid),
            )
            self._conn.commit()
            return pid
        pid = self._new_id()
        self._conn.execute(
            "INSERT INTO ports (id, target_id, port, protocol, state, service, product, version, extra_info, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pid,
                target_id,
                port,
                protocol,
                state,
                service,
                product,
                version,
                extra,
                now,
                now,
            ),
        )
        self._conn.commit()
        return pid

    def get_ports(self, target_id: str) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM ports WHERE target_id = ? ORDER BY port", (target_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Findings ──

    def add_finding(
        self,
        session_id: str,
        title: str,
        description: str = "",
        severity: str = "medium",
        category: str = "",
        cve_id: str = "",
        technique_id: str = "",
        mitre_tactic: str = "",
        confidence: str = "medium",
        target_id: Optional[str] = None,
    ) -> str:
        fid = self._new_id()
        now = self._now()
        self._conn.execute(
            "INSERT INTO findings (id, session_id, target_id, title, description, severity, category, cve_id, technique_id, mitre_tactic, confidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fid,
                session_id,
                target_id,
                title,
                description,
                severity,
                category,
                cve_id,
                technique_id,
                mitre_tactic,
                confidence,
                now,
            ),
        )
        self._conn.commit()
        return fid

    def get_findings(
        self, session_id: str, severity: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        if severity:
            rows = self._conn.execute(
                "SELECT * FROM findings WHERE session_id = ? AND severity = ? ORDER BY created_at DESC",
                (session_id, severity),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM findings WHERE session_id = ? ORDER BY created_at DESC",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def link_evidence_to_finding(self, finding_id: str, evidence_id: str):
        row = self._conn.execute(
            "SELECT evidence_ids FROM findings WHERE id = ?", (finding_id,)
        ).fetchone()
        if row:
            ids = json.loads(row["evidence_ids"])
            if evidence_id not in ids:
                ids.append(evidence_id)
                self._conn.execute(
                    "UPDATE findings SET evidence_ids = ? WHERE id = ?",
                    (json.dumps(ids), finding_id),
                )
                self._conn.commit()

    # ── Evidence ──

    def add_evidence(
        self,
        session_id: str,
        type: str,
        label: str,
        data: Dict[str, Any],
        source: str = "",
        finding_id: Optional[str] = None,
    ) -> str:
        eid = self._new_id()
        now = self._now()
        reference = self._evidence_store.capture(data, evidence_id=eid)
        self._conn.execute(
            "INSERT INTO evidence (id, session_id, finding_id, type, label, data, source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                eid,
                session_id,
                finding_id,
                type,
                label,
                reference.model_dump_json(),
                source,
                now,
            ),
        )
        self._conn.commit()
        if finding_id:
            self.link_evidence_to_finding(finding_id, eid)
        return eid

    def get_evidence(
        self, session_id: Optional[str] = None, finding_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        if finding_id:
            rows = self._conn.execute(
                "SELECT * FROM evidence WHERE finding_id = ? ORDER BY created_at",
                (finding_id,),
            ).fetchall()
        elif session_id:
            rows = self._conn.execute(
                "SELECT * FROM evidence WHERE session_id = ? ORDER BY created_at",
                (session_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM evidence ORDER BY created_at"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_session_context(self, session_id: str) -> Dict[str, Any]:
        session = self.get_session(session_id)
        if not session:
            return {}
        targets = self.get_targets(session_id)
        findings = self.get_findings(session_id)
        evidence = self.get_evidence(session_id=session_id)
        target_details = []
        for t in targets:
            ports = self.get_ports(t["id"])
            target_details.append({**t, "ports": ports})
        return {
            "session": session,
            "targets": target_details,
            "findings": findings,
            "evidence": evidence,
        }

    # ── Projects (engagement scope, spans sessions) ──

    def create_project(self, name: str = "", scope: str = "") -> str:
        pid = self._new_id()
        self._conn.execute(
            "INSERT INTO projects (id, name, scope, created_at) VALUES (?, ?, ?, ?)",
            (pid, name, scope, self._now()),
        )
        self._conn.commit()
        return pid

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_projects(self, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM projects ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Artifacts (durable engagement data: hosts, creds, tokens, ...) ──

    def add_artifact(
        self,
        type: str,
        key: str,
        value: str = "",
        session_id: Optional[str] = None,
        project_id: Optional[str] = None,
        sensitive: bool = False,
    ) -> str:
        aid = self._new_id()
        self._conn.execute(
            "INSERT INTO artifacts (id, project_id, session_id, type, key, value, sensitive, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (aid, project_id, session_id, type, key, value, 1 if sensitive else 0, self._now()),
        )
        self._conn.commit()
        return aid

    def get_artifacts(
        self,
        session_id: Optional[str] = None,
        project_id: Optional[str] = None,
        type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        clauses, params = [], []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if type:
            clauses.append("type = ?")
            params.append(type)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        # safe: column names are literals; only values are parameterized
        rows = self._conn.execute(
            f"SELECT * FROM artifacts{where} ORDER BY created_at",  # nosec B608
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Durable plans and safe recovery ─────────────────────────────────

    def save_plan(self, session_id: str, plan: Dict[str, Any]) -> List[str]:
        """Persist a plan and return node IDs whose material action changed."""
        existing = {
            row["node_id"]: row["material_fingerprint"]
            for row in self._conn.execute(
                "SELECT node_id, material_fingerprint FROM mission_nodes WHERE session_id = ?",
                (session_id,),
            ).fetchall()
        }
        changed: List[str] = []
        now = self._now()
        self._conn.execute(
            "INSERT INTO missions (session_id, plan_json, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET plan_json = excluded.plan_json, updated_at = excluded.updated_at",
            (session_id, json.dumps(plan, sort_keys=True), now),
        )
        for node_id, node in plan.get("nodes", {}).items():
            fingerprint = node.get("material_fingerprint", "")
            if not fingerprint:
                raise ValueError("persisted plan nodes require material_fingerprint")
            prior = existing.get(node_id)
            status = node.get("status", "pending") if prior == fingerprint else "pending"
            if prior is not None and prior != fingerprint:
                changed.append(node_id)
            self._conn.execute(
                "INSERT INTO mission_nodes (session_id, node_id, material_fingerprint, idempotency_key, status, attempts, result_summary, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 0, '', ?) "
                "ON CONFLICT(session_id, node_id) DO UPDATE SET material_fingerprint = excluded.material_fingerprint, "
                "idempotency_key = excluded.idempotency_key, status = CASE WHEN mission_nodes.material_fingerprint = excluded.material_fingerprint THEN mission_nodes.status ELSE excluded.status END, "
                "updated_at = excluded.updated_at",
                (session_id, node_id, fingerprint, node.get("idempotency_key", ""), status, now),
            )
        self._conn.commit()
        return changed

    def load_plan(self, session_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT plan_json FROM missions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if not row:
            return None
        plan = json.loads(row["plan_json"])
        states = self._conn.execute(
            "SELECT node_id, status, attempts, result_summary FROM mission_nodes WHERE session_id = ?",
            (session_id,),
        ).fetchall()
        for state in states:
            node = plan.get("nodes", {}).get(state["node_id"])
            if node is not None:
                node["status"] = state["status"]
                node["result_summary"] = state["result_summary"]
        return plan

    def checkpoint_plan_node(
        self,
        session_id: str,
        node_id: str,
        status: str,
        summary: str = "",
        increment_attempts: bool = False,
    ) -> None:
        now = self._now()
        self._conn.execute(
            "UPDATE mission_nodes SET status = ?, result_summary = ?, attempts = attempts + ?, updated_at = ? "
            "WHERE session_id = ? AND node_id = ?",
            (status, summary, 1 if increment_attempts else 0, now, session_id, node_id),
        )
        self._conn.commit()

    def recover_interrupted_plan(self, session_id: str) -> List[str]:
        """Fence interrupted work: never replay an ambiguous operation automatically."""
        rows = self._conn.execute(
            "SELECT node_id FROM mission_nodes WHERE session_id = ? AND status = 'running'",
            (session_id,),
        ).fetchall()
        node_ids = [row["node_id"] for row in rows]
        if node_ids:
            self._conn.execute(
                "UPDATE mission_nodes SET status = 'needs_review', result_summary = 'interrupted while running; verify before retry', updated_at = ? "
                "WHERE session_id = ? AND status = 'running'",
                (self._now(), session_id),
            )
            self._conn.commit()
        return node_ids

    def reset_retryable_node(self, session_id: str, node_id: str, max_attempts: int) -> bool:
        row = self._conn.execute(
            "SELECT status, attempts FROM mission_nodes WHERE session_id = ? AND node_id = ?",
            (session_id, node_id),
        ).fetchone()
        if not row or row["status"] not in {"error", "timeout"} or row["attempts"] >= max_attempts:
            return False
        self.checkpoint_plan_node(session_id, node_id, "pending", "retry requested")
        return True

    # ── Project-isolated knowledge and memory lifecycle ─────────────────

    def add_project_knowledge_node(
        self, project_id: str, type: str, name: str, description: str = "", provenance: Optional[Dict[str, Any]] = None
    ) -> str:
        node_id = self._new_id()
        self._conn.execute(
            "INSERT INTO project_knowledge_nodes (id, project_id, type, name, description, provenance, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (node_id, project_id, type, name, description, json.dumps(provenance or {}), self._now()),
        )
        self._conn.commit()
        return node_id

    def add_project_knowledge_edge(
        self, project_id: str, source_id: str, target_id: str, relationship: str, provenance: Optional[Dict[str, Any]] = None
    ) -> str:
        edge_id = self._new_id()
        self._conn.execute(
            "INSERT INTO project_knowledge_edges (id, project_id, source_id, target_id, relationship, provenance, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (edge_id, project_id, source_id, target_id, relationship, json.dumps(provenance or {}), self._now()),
        )
        self._conn.commit()
        return edge_id

    def search_project_knowledge(self, project_id: str, query: str) -> List[Dict[str, Any]]:
        words = [word for word in query.lower().split() if word]
        if not words:
            return []
        clauses = " OR ".join("LOWER(name || ' ' || description) LIKE ?" for _ in words)
        rows = self._conn.execute(
            f"SELECT * FROM project_knowledge_nodes WHERE project_id = ? AND ({clauses}) ORDER BY created_at DESC LIMIT 20",  # nosec B608
            [project_id, *[f"%{word}%" for word in words]],
        ).fetchall()
        return [dict(row) for row in rows]

    def record_memory_event(self, project_id: str, event: str, detail: str = "") -> str:
        event_id = self._new_id()
        self._conn.execute(
            "INSERT INTO memory_events (id, project_id, event, detail, created_at) VALUES (?, ?, ?, ?, ?)",
            (event_id, project_id, event, detail, self._now()),
        )
        self._conn.commit()
        return event_id

    def export_project(self, project_id: str, include_sensitive: bool = False) -> Dict[str, Any]:
        project = self.get_project(project_id)
        if project is None:
            raise ValueError("unknown project")
        artifacts = self.get_artifacts(project_id=project_id)
        if not include_sensitive:
            artifacts = [{**item, "value": "[REDACTED]"} if item["sensitive"] else item for item in artifacts]
        nodes = self._conn.execute(
            "SELECT * FROM project_knowledge_nodes WHERE project_id = ? ORDER BY created_at", (project_id,)
        ).fetchall()
        edges = self._conn.execute(
            "SELECT * FROM project_knowledge_edges WHERE project_id = ? ORDER BY created_at", (project_id,)
        ).fetchall()
        self.record_memory_event(project_id, "export", "sensitive=" + str(include_sensitive).lower())
        return {"project": project, "artifacts": artifacts, "knowledge_nodes": [dict(row) for row in nodes], "knowledge_edges": [dict(row) for row in edges]}

    def compress_project_artifacts(self, project_id: str) -> Optional[str]:
        artifacts = self.get_artifacts(project_id=project_id)
        if not artifacts:
            return None
        types = sorted({item["type"] for item in artifacts})
        summary = f"{len(artifacts)} retained artifacts across: {', '.join(types)}"
        artifact_id = self.add_artifact("memory_summary", "project_summary", summary, project_id=project_id)
        self.record_memory_event(project_id, "compression", "source_artifacts=" + str(len(artifacts)))
        return artifact_id

    def delete_project_memory(self, project_id: str) -> int:
        artifacts = self._conn.execute("SELECT COUNT(*) AS count FROM artifacts WHERE project_id = ?", (project_id,)).fetchone()["count"]
        self.record_memory_event(project_id, "deletion_requested", "artifact_count=" + str(artifacts))
        self._conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        self._conn.commit()
        return artifacts
    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
