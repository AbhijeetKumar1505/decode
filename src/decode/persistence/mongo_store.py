"""MongoDB-backed operational store.

`MongoSessionStore` mirrors the public API of :class:`SessionStore` field for
field so it is a drop-in backend. Raw evidence is never uploaded: it is captured
locally through :class:`ProtectedEvidenceStore` and only its hashed reference is
stored in MongoDB. Serialization mirrors the SQLite store (JSON strings where the
SQLite store used JSON columns) so downstream consumers behave identically.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from .evidence import ProtectedEvidenceStore

_DEFAULT_DB = "decode"
_NO_ID = {"_id": 0}


def build_mongo_uri(uri: str | None = None, password: str | None = None) -> str:
    """Resolve the connection string, substituting a password placeholder.

    Reads ``MONGODB_URI`` / ``MONGODB_PASSWORD`` from the environment when not
    passed explicitly. The password is URL-encoded before substitution.
    """
    uri = uri if uri is not None else os.getenv("MONGODB_URI", "")
    password = password if password is not None else os.getenv("MONGODB_PASSWORD", "")
    if not uri:
        raise ValueError("MONGODB_URI is not configured")
    for placeholder in ("<db_password>", "<password>"):
        if placeholder in uri and password:
            uri = uri.replace(placeholder, quote_plus(password))
    return uri


def mongo_client_from_env(**kwargs: Any):
    """Create a MongoClient from environment configuration."""
    from pymongo import MongoClient
    from pymongo.server_api import ServerApi

    # Fail fast (5s) so a misconfigured/unreachable cluster does not hang startup;
    # callers may override via kwargs.
    options: dict[str, Any] = {
        "server_api": ServerApi("1"),
        "serverSelectionTimeoutMS": 5000,
    }
    options.update(kwargs)
    return MongoClient(build_mongo_uri(), **options)


class MongoSessionStore:
    """Operational store backed by MongoDB with the SessionStore contract."""

    def __init__(
        self,
        client: Any = None,
        db_name: str | None = None,
        evidence_path: Path | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client if client is not None else mongo_client_from_env()
        self._db = self._client[db_name or os.getenv("MONGODB_DB", _DEFAULT_DB)]
        self._evidence_store = ProtectedEvidenceStore(
            evidence_path or Path("data/evidence")
        )
        try:
            self._init_indexes()  # first real round-trip; surfaces connection errors here
        except Exception:
            if self._owns_client:
                self._client.close()
            raise

    def _init_indexes(self) -> None:
        self._db.targets.create_index("session_id")
        self._db.ports.create_index("target_id")
        self._db.findings.create_index("session_id")
        self._db.evidence.create_index("session_id")
        self._db.evidence.create_index("finding_id")
        self._db.artifacts.create_index("project_id")
        self._db.artifacts.create_index("session_id")
        self._db.mission_nodes.create_index(
            [("session_id", 1), ("node_id", 1)], unique=True
        )
        self._db.project_knowledge_nodes.create_index("project_id")
        self._db.project_knowledge_edges.create_index("project_id")

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()

    def _new_id(self) -> str:
        return str(uuid.uuid4())

    # ── Sessions ──

    def create_session(self, goal: str = "", target_focus: str = "") -> str:
        sid = self._new_id()
        now = self._now()
        self._db.sessions.insert_one(
            {
                "_id": sid,
                "id": sid,
                "goal": goal,
                "target_focus": target_focus,
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }
        )
        return sid

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        return self._db.sessions.find_one({"_id": session_id}, _NO_ID)

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(
            self._db.sessions.find({}, _NO_ID).sort("created_at", -1).limit(limit)
        )

    def update_session(self, session_id: str, **kwargs: Any) -> None:
        allowed = {"goal", "target_focus", "status"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = self._now()
        self._db.sessions.update_one({"_id": session_id}, {"$set": updates})

    def close_session(self, session_id: str) -> None:
        self.update_session(session_id, status="closed")

    # ── Targets ──

    def upsert_target(
        self,
        session_id: str,
        hostname: str = "",
        ip: str = "",
        domain: str = "",
        os: str = "",
        metadata: dict | None = None,
    ) -> str:
        existing = self._db.targets.find_one(
            {
                "session_id": session_id,
                "$or": [{"hostname": hostname}, {"ip_address": ip}],
                "hostname": {"$ne": ""},
            }
        )
        now = self._now()
        if existing:
            tid = existing["_id"]
            update = {"last_seen": now, "metadata": json.dumps(metadata or {})}
            if os:
                update["os"] = os
            self._db.targets.update_one({"_id": tid}, {"$set": update})
            return tid
        tid = self._new_id()
        self._db.targets.insert_one(
            {
                "_id": tid,
                "id": tid,
                "session_id": session_id,
                "hostname": hostname,
                "ip_address": ip,
                "domain": domain,
                "os": os,
                "first_seen": now,
                "last_seen": now,
                "metadata": json.dumps(metadata or {}),
            }
        )
        return tid

    def get_target(self, target_id: str) -> dict[str, Any] | None:
        row = self._db.targets.find_one({"_id": target_id}, _NO_ID)
        if row:
            row["metadata"] = json.loads(row.get("metadata", "{}"))
        return row

    def get_targets(self, session_id: str) -> list[dict[str, Any]]:
        return list(
            self._db.targets.find({"session_id": session_id}, _NO_ID).sort(
                "last_seen", -1
            )
        )

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
        existing = self._db.ports.find_one(
            {"target_id": target_id, "port": port, "protocol": protocol}
        )
        now = self._now()
        if existing:
            pid = existing["_id"]
            self._db.ports.update_one(
                {"_id": pid},
                {
                    "$set": {
                        "state": state,
                        "service": service,
                        "product": product,
                        "version": version,
                        "extra_info": extra,
                        "last_seen": now,
                    }
                },
            )
            return pid
        pid = self._new_id()
        self._db.ports.insert_one(
            {
                "_id": pid,
                "id": pid,
                "target_id": target_id,
                "port": port,
                "protocol": protocol,
                "state": state,
                "service": service,
                "product": product,
                "version": version,
                "extra_info": extra,
                "first_seen": now,
                "last_seen": now,
            }
        )
        return pid

    def get_ports(self, target_id: str) -> list[dict[str, Any]]:
        return list(
            self._db.ports.find({"target_id": target_id}, _NO_ID).sort("port", 1)
        )

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
        target_id: str | None = None,
    ) -> str:
        fid = self._new_id()
        self._db.findings.insert_one(
            {
                "_id": fid,
                "id": fid,
                "session_id": session_id,
                "target_id": target_id,
                "title": title,
                "description": description,
                "severity": severity,
                "category": category,
                "cve_id": cve_id,
                "technique_id": technique_id,
                "mitre_tactic": mitre_tactic,
                "confidence": confidence,
                "evidence_ids": "[]",
                "created_at": self._now(),
            }
        )
        return fid

    def get_findings(
        self, session_id: str, severity: str | None = None
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"session_id": session_id}
        if severity:
            query["severity"] = severity
        return list(self._db.findings.find(query, _NO_ID).sort("created_at", -1))

    def link_evidence_to_finding(self, finding_id: str, evidence_id: str) -> None:
        row = self._db.findings.find_one({"_id": finding_id}, {"evidence_ids": 1})
        if not row:
            return
        ids = json.loads(row.get("evidence_ids", "[]"))
        if evidence_id not in ids:
            ids.append(evidence_id)
            self._db.findings.update_one(
                {"_id": finding_id}, {"$set": {"evidence_ids": json.dumps(ids)}}
            )

    # ── Evidence ──

    def add_evidence(
        self,
        session_id: str,
        type: str,
        label: str,
        data: dict[str, Any],
        source: str = "",
        finding_id: str | None = None,
    ) -> str:
        eid = self._new_id()
        now = self._now()
        reference = self._evidence_store.capture(data, evidence_id=eid)
        self._db.evidence.insert_one(
            {
                "_id": eid,
                "id": eid,
                "session_id": session_id,
                "finding_id": finding_id,
                "type": type,
                "label": label,
                "data": reference.model_dump_json(),
                "source": source,
                "created_at": now,
            }
        )
        if finding_id:
            self.link_evidence_to_finding(finding_id, eid)
        return eid

    def get_evidence(
        self, session_id: str | None = None, finding_id: str | None = None
    ) -> list[dict[str, Any]]:
        if finding_id:
            query: dict[str, Any] = {"finding_id": finding_id}
        elif session_id:
            query = {"session_id": session_id}
        else:
            query = {}
        return list(self._db.evidence.find(query, _NO_ID).sort("created_at", 1))

    def get_session_context(self, session_id: str) -> dict[str, Any]:
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

    # ── Projects ──

    def create_project(self, name: str = "", scope: str = "") -> str:
        pid = self._new_id()
        self._db.projects.insert_one(
            {
                "_id": pid,
                "id": pid,
                "name": name,
                "scope": scope,
                "created_at": self._now(),
            }
        )
        return pid

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        return self._db.projects.find_one({"_id": project_id}, _NO_ID)

    def list_projects(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(
            self._db.projects.find({}, _NO_ID).sort("created_at", -1).limit(limit)
        )

    # ── Artifacts ──

    def add_artifact(
        self,
        type: str,
        key: str,
        value: str = "",
        session_id: str | None = None,
        project_id: str | None = None,
        sensitive: bool = False,
    ) -> str:
        aid = self._new_id()
        self._db.artifacts.insert_one(
            {
                "_id": aid,
                "id": aid,
                "project_id": project_id,
                "session_id": session_id,
                "type": type,
                "key": key,
                "value": value,
                "sensitive": 1 if sensitive else 0,
                "created_at": self._now(),
            }
        )
        return aid

    def get_artifacts(
        self,
        session_id: str | None = None,
        project_id: str | None = None,
        type: str | None = None,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {}
        if session_id:
            query["session_id"] = session_id
        if project_id:
            query["project_id"] = project_id
        if type:
            query["type"] = type
        return list(self._db.artifacts.find(query, _NO_ID).sort("created_at", 1))

    # ── Durable plans and safe recovery ──

    def save_plan(self, session_id: str, plan: dict[str, Any]) -> list[str]:
        existing = {
            doc["node_id"]: doc
            for doc in self._db.mission_nodes.find({"session_id": session_id})
        }
        changed: list[str] = []
        now = self._now()
        self._db.missions.update_one(
            {"_id": session_id},
            {
                "$set": {
                    "session_id": session_id,
                    "plan_json": json.dumps(plan, sort_keys=True),
                    "updated_at": now,
                }
            },
            upsert=True,
        )
        for node_id, node in plan.get("nodes", {}).items():
            fingerprint = node.get("material_fingerprint", "")
            if not fingerprint:
                raise ValueError("persisted plan nodes require material_fingerprint")
            prior = existing.get(node_id)
            prior_fp = prior["material_fingerprint"] if prior else None
            if prior_fp is not None and prior_fp != fingerprint:
                changed.append(node_id)
            if prior is None:
                self._db.mission_nodes.insert_one(
                    {
                        "_id": f"{session_id}:{node_id}",
                        "session_id": session_id,
                        "node_id": node_id,
                        "material_fingerprint": fingerprint,
                        "idempotency_key": node.get("idempotency_key", ""),
                        "status": "pending",
                        "attempts": 0,
                        "result_summary": "",
                        "updated_at": now,
                    }
                )
            else:
                status = prior["status"] if prior_fp == fingerprint else "pending"
                self._db.mission_nodes.update_one(
                    {"_id": f"{session_id}:{node_id}"},
                    {
                        "$set": {
                            "material_fingerprint": fingerprint,
                            "idempotency_key": node.get("idempotency_key", ""),
                            "status": status,
                            "updated_at": now,
                        }
                    },
                )
        return changed

    def load_plan(self, session_id: str) -> dict[str, Any] | None:
        mission = self._db.missions.find_one({"_id": session_id})
        if not mission:
            return None
        plan = json.loads(mission["plan_json"])
        for state in self._db.mission_nodes.find({"session_id": session_id}):
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
        self._db.mission_nodes.update_one(
            {"_id": f"{session_id}:{node_id}"},
            {
                "$set": {
                    "status": status,
                    "result_summary": summary,
                    "updated_at": self._now(),
                },
                "$inc": {"attempts": 1 if increment_attempts else 0},
            },
        )

    def recover_interrupted_plan(self, session_id: str) -> list[str]:
        running = list(
            self._db.mission_nodes.find(
                {"session_id": session_id, "status": "running"}, {"node_id": 1}
            )
        )
        node_ids = [doc["node_id"] for doc in running]
        if node_ids:
            self._db.mission_nodes.update_many(
                {"session_id": session_id, "status": "running"},
                {
                    "$set": {
                        "status": "needs_review",
                        "result_summary": "interrupted while running; verify before retry",
                        "updated_at": self._now(),
                    }
                },
            )
        return node_ids

    def reset_retryable_node(
        self, session_id: str, node_id: str, max_attempts: int
    ) -> bool:
        row = self._db.mission_nodes.find_one({"_id": f"{session_id}:{node_id}"})
        if (
            not row
            or row["status"] not in {"error", "timeout"}
            or row["attempts"] >= max_attempts
        ):
            return False
        self.checkpoint_plan_node(session_id, node_id, "pending", "retry requested")
        return True

    # ── Project-isolated knowledge and memory lifecycle ──

    def add_project_knowledge_node(
        self,
        project_id: str,
        type: str,
        name: str,
        description: str = "",
        provenance: dict[str, Any] | None = None,
    ) -> str:
        node_id = self._new_id()
        self._db.project_knowledge_nodes.insert_one(
            {
                "_id": node_id,
                "id": node_id,
                "project_id": project_id,
                "type": type,
                "name": name,
                "description": description,
                "provenance": json.dumps(provenance or {}),
                "created_at": self._now(),
            }
        )
        return node_id

    def add_project_knowledge_edge(
        self,
        project_id: str,
        source_id: str,
        target_id: str,
        relationship: str,
        provenance: dict[str, Any] | None = None,
    ) -> str:
        edge_id = self._new_id()
        self._db.project_knowledge_edges.insert_one(
            {
                "_id": edge_id,
                "id": edge_id,
                "project_id": project_id,
                "source_id": source_id,
                "target_id": target_id,
                "relationship": relationship,
                "provenance": json.dumps(provenance or {}),
                "created_at": self._now(),
            }
        )
        return edge_id

    def search_project_knowledge(
        self, project_id: str, query: str
    ) -> list[dict[str, Any]]:
        words = [word for word in query.lower().split() if word]
        if not words:
            return []
        clauses = [
            {
                "$or": [
                    {"name": {"$regex": re.escape(word), "$options": "i"}},
                    {"description": {"$regex": re.escape(word), "$options": "i"}},
                ]
            }
            for word in words
        ]
        rows = (
            self._db.project_knowledge_nodes.find(
                {"project_id": project_id, "$or": clauses}, _NO_ID
            )
            .sort("created_at", -1)
            .limit(20)
        )
        return list(rows)

    def record_memory_event(self, project_id: str, event: str, detail: str = "") -> str:
        event_id = self._new_id()
        self._db.memory_events.insert_one(
            {
                "_id": event_id,
                "id": event_id,
                "project_id": project_id,
                "event": event,
                "detail": detail,
                "created_at": self._now(),
            }
        )
        return event_id

    def export_project(
        self, project_id: str, include_sensitive: bool = False
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        if project is None:
            raise ValueError("unknown project")
        artifacts = self.get_artifacts(project_id=project_id)
        if not include_sensitive:
            artifacts = [
                {**item, "value": "[REDACTED]"} if item["sensitive"] else item
                for item in artifacts
            ]
        nodes = list(
            self._db.project_knowledge_nodes.find(
                {"project_id": project_id}, _NO_ID
            ).sort("created_at", 1)
        )
        edges = list(
            self._db.project_knowledge_edges.find(
                {"project_id": project_id}, _NO_ID
            ).sort("created_at", 1)
        )
        self.record_memory_event(
            project_id, "export", "sensitive=" + str(include_sensitive).lower()
        )
        return {
            "project": project,
            "artifacts": artifacts,
            "knowledge_nodes": nodes,
            "knowledge_edges": edges,
        }

    def compress_project_artifacts(self, project_id: str) -> str | None:
        artifacts = self.get_artifacts(project_id=project_id)
        if not artifacts:
            return None
        types = sorted({item["type"] for item in artifacts})
        summary = f"{len(artifacts)} retained artifacts across: {', '.join(types)}"
        artifact_id = self.add_artifact(
            "memory_summary", "project_summary", summary, project_id=project_id
        )
        self.record_memory_event(
            project_id, "compression", "source_artifacts=" + str(len(artifacts))
        )
        return artifact_id

    def delete_project_memory(self, project_id: str) -> int:
        artifacts = self._db.artifacts.count_documents({"project_id": project_id})
        self.record_memory_event(
            project_id, "deletion_requested", "artifact_count=" + str(artifacts)
        )
        self._db.artifacts.delete_many({"project_id": project_id})
        self._db.project_knowledge_edges.delete_many({"project_id": project_id})
        self._db.project_knowledge_nodes.delete_many({"project_id": project_id})
        self._db.memory_events.delete_many({"project_id": project_id})
        self._db.projects.delete_one({"_id": project_id})
        return artifacts

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
