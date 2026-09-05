"""Scoped memory layers and provenance-preserving retrieval."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from ..persistence.store import SessionStore

SENSITIVE_TYPES = {
    "credential",
    "token",
    "cookie",
    "jwt",
    "api_key",
    "password",
    "secret",
}


class SessionMemory:
    """Volatile per-mission scratchpad."""

    def __init__(self, session_id: str | None = None) -> None:
        self.session_id = session_id
        self._scratch: dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        self._scratch[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._scratch.get(key, default)

    def all(self) -> dict[str, Any]:
        return dict(self._scratch)


class ProjectMemory:
    """Durable artifacts isolated to one engagement project."""

    def __init__(self, store: SessionStore, project_id: str | None = None) -> None:
        self._store = store
        self.project_id = project_id

    def remember(
        self,
        type: str,
        key: str,
        value: str = "",
        session_id: str | None = None,
        sensitive: bool | None = None,
    ) -> str:
        if sensitive is None:
            sensitive = type in SENSITIVE_TYPES
        return self._store.add_artifact(
            type=type,
            key=key,
            value=value,
            session_id=session_id,
            project_id=self.project_id,
            sensitive=sensitive,
        )

    def recall(self, type: str | None = None) -> list[dict[str, Any]]:
        return self._store.get_artifacts(project_id=self.project_id, type=type)

    def exact(self, query: str) -> list[dict[str, Any]]:
        normalized = query.casefold().strip()
        if not normalized:
            return []
        return [
            item
            for item in self.recall()
            if normalized in item["key"].casefold()
            or normalized in item["value"].casefold()
        ]

    def hosts(self) -> list[dict[str, Any]]:
        return self.recall(type="host")

    def credentials(self) -> list[dict[str, Any]]:
        return self.recall(type="credential")


class KnowledgeMemory:
    """Legacy non-project graph facade retained for compatibility."""

    def __init__(self, graph: Any = None) -> None:
        if graph is None:
            from ..knowledge.graph import KnowledgeGraph

            graph = KnowledgeGraph()
        self._graph = graph

    def learn(
        self, name: str, description: str = "", type: str = "finding", **properties: Any
    ) -> str:
        from ..knowledge.graph import KnowledgeNode

        node = KnowledgeNode(
            type=type, name=name, description=description, properties=properties
        )
        self._graph.add_node(node)
        return node.id

    def search(self, query: str) -> list[dict[str, Any]]:
        return [node.model_dump() for node in self._graph.search(query)]


class ProjectKnowledgeMemory:
    """SQLite-backed graph whose nodes and edges cannot cross project boundaries."""

    def __init__(self, store: SessionStore, project_id: str) -> None:
        self._store = store
        self.project_id = project_id

    def learn(
        self,
        name: str,
        description: str = "",
        type: str = "finding",
        provenance: dict[str, Any] | None = None,
    ) -> str:
        provenance = provenance or {"source": "user", "verification": "unverified"}
        return self._store.add_project_knowledge_node(
            self.project_id, type, name, description, provenance
        )

    def relate(
        self,
        source_id: str,
        target_id: str,
        relationship: str,
        provenance: dict[str, Any] | None = None,
    ) -> str:
        return self._store.add_project_knowledge_edge(
            self.project_id,
            source_id,
            target_id,
            relationship,
            provenance or {"source": "user", "verification": "unverified"},
        )

    def search(self, query: str) -> list[dict[str, Any]]:
        nodes = self._store.search_project_knowledge(self.project_id, query)
        for node in nodes:
            node["provenance"] = json.loads(node["provenance"])
        return nodes


class HybridRetriever:
    """Exact artifacts, project graph, and opt-in semantic results with provenance."""

    def __init__(
        self,
        project: ProjectMemory,
        knowledge: ProjectKnowledgeMemory,
        semantic_search: Callable[[str], list[dict[str, Any]]] | None = None,
    ) -> None:
        self._project = project
        self._knowledge = knowledge
        self._semantic_search = semantic_search

    def retrieve(self, query: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for artifact in self._project.exact(query):
            results.append(
                {
                    "source": "exact_artifact",
                    "record": artifact,
                    "provenance": {
                        "artifact_id": artifact["id"],
                        "sensitive": bool(artifact["sensitive"]),
                    },
                }
            )
        for node in self._knowledge.search(query):
            results.append(
                {
                    "source": "project_graph",
                    "record": node,
                    "provenance": node["provenance"],
                }
            )
        if self._semantic_search is not None:
            for item in self._semantic_search(query):
                results.append(
                    {
                        "source": "semantic",
                        "record": item,
                        "provenance": {
                            "verification": "unverified",
                            "retrieval": "optional_semantic",
                        },
                    }
                )
        return results


class MemoryManager:
    """Facade tying session, project, graph, retrieval, and lifecycle controls together."""

    def __init__(
        self,
        store: SessionStore,
        session_id: str | None = None,
        project_id: str | None = None,
        knowledge: Any = None,
        semantic_search: Callable[[str], list[dict[str, Any]]] | None = None,
    ) -> None:
        self._store = store
        self.session = SessionMemory(session_id)
        self.project = ProjectMemory(store, project_id)
        self.knowledge = (
            knowledge
            if knowledge is not None
            else ProjectKnowledgeMemory(store, project_id)
            if project_id
            else KnowledgeMemory()
        )
        self.retriever = (
            HybridRetriever(self.project, self.knowledge, semantic_search)
            if isinstance(self.knowledge, ProjectKnowledgeMemory)
            else None
        )

    @property
    def session_id(self) -> str | None:
        return self.session.session_id

    def capture_host(self, host: str) -> str | None:
        if not host:
            return None
        return self.project.remember("host", key=host, session_id=self.session_id)

    def retrieve(self, query: str) -> list[dict[str, Any]]:
        return self.retriever.retrieve(query) if self.retriever is not None else []

    def export(self, include_sensitive: bool = False) -> dict[str, Any]:
        if not self.project.project_id:
            raise ValueError("project-scoped memory is required for export")
        return self._store.export_project(self.project.project_id, include_sensitive)

    def compress(self) -> str | None:
        if not self.project.project_id:
            raise ValueError("project-scoped memory is required for compression")
        return self._store.compress_project_artifacts(self.project.project_id)

    def delete(self) -> int:
        if not self.project.project_id:
            raise ValueError("project-scoped memory is required for deletion")
        return self._store.delete_project_memory(self.project.project_id)
