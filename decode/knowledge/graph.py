import json
from typing import Dict, Any, List, Optional, Set
from pathlib import Path
from datetime import datetime
from pydantic import BaseModel, Field
from uuid import uuid4


class KnowledgeNode(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: str
    name: str
    description: str = ""
    properties: Dict[str, Any] = Field(default_factory=dict)
    source: str = "internal"
    created: str = Field(default_factory=lambda: datetime.now().isoformat())


class KnowledgeEdge(BaseModel):
    source_id: str
    target_id: str
    relationship: str
    properties: Dict[str, Any] = Field(default_factory=dict)


NODE_TYPES = {
    "asset",
    "threat",
    "technique",
    "mitigation",
    "vulnerability",
    "tool",
    "finding",
    "cve",
}


class KnowledgeGraph:
    def __init__(self, path: Optional[Path] = None):
        self._path = path or Path("data/knowledge_graph.json")
        self._nodes: Dict[str, KnowledgeNode] = {}
        self._edges: List[KnowledgeEdge] = []
        self._index: Dict[str, Set[str]] = {}
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
                for n in data.get("nodes", []):
                    node = KnowledgeNode(**n)
                    self._nodes[node.id] = node
                for e in data.get("edges", []):
                    self._edges.append(KnowledgeEdge(**e))
            except Exception:
                pass
        if not self._nodes:
            self._seed_knowledge()
        else:
            self._rebuild_index()

    def _seed_knowledge(self):
        seed = [
            KnowledgeNode(
                id="threat-prompt-injection",
                type="threat",
                name="Prompt Injection",
                description="Attacker manipulates LLM through crafted inputs",
                source="OWASP LLM Top 10",
                properties={"ref": "OWASP-LLM-01"},
            ),
            KnowledgeNode(
                id="threat-data-poisoning",
                type="threat",
                name="Data Poisoning",
                description="Attacker corrupts training or retrieval data",
                source="MITRE ATLAS",
                properties={"ref": "ATLAS-T003"},
            ),
            KnowledgeNode(
                id="mitigation-input-sanitization",
                type="mitigation",
                name="Input Sanitization",
                description="Validate and sanitize all user inputs before processing",
            ),
            KnowledgeNode(
                id="mitigation-rag-isolation",
                type="mitigation",
                name="RAG Pipeline Isolation",
                description="Isolate retrieval pipeline from untrusted data sources",
            ),
            KnowledgeNode(
                id="technique-prompt-inject",
                type="technique",
                name="Direct Prompt Injection",
                description="Embed injection in user input that overrides system prompt",
                properties={"mitre-atlas": "ATLAS-T001"},
            ),
            KnowledgeNode(
                id="technique-indirect-inject",
                type="technique",
                name="Indirect Prompt Injection",
                description="Injection through retrieved external content",
                properties={"mitre-atlas": "ATLAS-T002"},
            ),
            KnowledgeNode(
                id="cve-sqli-generic",
                type="cve",
                name="SQL Injection",
                description="SQL injection vulnerability in web applications",
                properties={"severity": "high"},
            ),
            KnowledgeNode(
                id="cve-xss-generic",
                type="cve",
                name="Cross-Site Scripting",
                description="XSS vulnerability allowing script execution",
                properties={"severity": "medium"},
            ),
            KnowledgeNode(
                id="tool-nmap",
                type="tool",
                name="Nmap",
                description="Network discovery and security scanning tool",
                properties={"category": "scanning"},
            ),
            KnowledgeNode(
                id="tool-burp",
                type="tool",
                name="Burp Suite",
                description="Web application security testing platform",
                properties={"category": "web"},
            ),
            KnowledgeNode(
                id="mitre-attack-discovery",
                type="technique",
                name="T1046 - Network Service Scanning",
                description="Adversaries may scan victims for network services",
                properties={"tactic": "Discovery"},
            ),
        ]
        for node in seed:
            self._nodes[node.id] = node

        seed_edges = [
            KnowledgeEdge(
                source_id="threat-prompt-injection",
                target_id="technique-prompt-inject",
                relationship="uses",
            ),
            KnowledgeEdge(
                source_id="threat-prompt-injection",
                target_id="technique-indirect-inject",
                relationship="uses",
            ),
            KnowledgeEdge(
                source_id="technique-prompt-inject",
                target_id="mitigation-input-sanitization",
                relationship="mitigated_by",
            ),
            KnowledgeEdge(
                source_id="technique-indirect-inject",
                target_id="mitigation-rag-isolation",
                relationship="mitigated_by",
            ),
            KnowledgeEdge(
                source_id="threat-data-poisoning",
                target_id="mitigation-rag-isolation",
                relationship="mitigated_by",
            ),
        ]
        self._edges = seed_edges
        self._rebuild_index()
        self._save()

    def _rebuild_index(self):
        self._index.clear()
        for node in self._nodes.values():
            for word in (node.name + " " + node.description).lower().split():
                if word not in self._index:
                    self._index[word] = set()
                self._index[word].add(node.id)

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "nodes": [n.model_dump() for n in self._nodes.values()],
            "edges": [e.model_dump() for e in self._edges],
        }
        self._path.write_text(json.dumps(data, indent=2))

    def add_node(self, node: KnowledgeNode):
        self._nodes[node.id] = node
        self._rebuild_index()
        self._save()

    def add_edge(self, edge: KnowledgeEdge):
        self._edges.append(edge)
        self._save()

    def search(self, query: str) -> List[KnowledgeNode]:
        words = query.lower().split()
        if not words:
            return []
        matching_ids: Optional[Set[str]] = None
        for word in words:
            ids = self._index.get(word, set())
            if matching_ids is None:
                matching_ids = set(ids)
            else:
                matching_ids &= ids
        if not matching_ids:
            matching_ids = set()
            for word in words:
                matching_ids.update(self._index.get(word, set()))
        return [self._nodes[nid] for nid in matching_ids if nid in self._nodes][:10]

    def get_related(self, node_id: str, max_depth: int = 2) -> Dict[str, Any]:
        visited: Set[str] = set()
        queue = [(node_id, 0)]
        related_nodes = []
        related_edges = []
        while queue:
            current_id, depth = queue.pop(0)
            if current_id in visited or depth > max_depth:
                continue
            visited.add(current_id)
            if current_id in self._nodes:
                related_nodes.append(self._nodes[current_id])
            for edge in self._edges:
                if edge.source_id == current_id:
                    related_edges.append(edge)
                    queue.append((edge.target_id, depth + 1))
                elif edge.target_id == current_id:
                    related_edges.append(edge)
                    queue.append((edge.source_id, depth + 1))
        return {
            "nodes": [n.model_dump() for n in related_nodes],
            "edges": [e.model_dump() for e in related_edges],
        }

    def find_path(self, source_id: str, target_id: str) -> List[List[str]]:
        paths = []
        queue = [[source_id]]
        while queue:
            path = queue.pop(0)
            last = path[-1]
            if last == target_id:
                paths.append(path)
                continue
            for edge in self._edges:
                if edge.source_id == last and edge.target_id not in path:
                    queue.append(path + [edge.target_id])
                elif edge.target_id == last and edge.source_id not in path:
                    queue.append(path + [edge.source_id])
        return paths[:5]

    def query(self, query: str) -> Dict[str, Any]:
        nodes = self.search(query)
        all_edges = []
        node_ids = {n.id for n in nodes}
        for edge in self._edges:
            if edge.source_id in node_ids or edge.target_id in node_ids:
                all_edges.append(edge)
        return {
            "nodes": [n.model_dump() for n in nodes],
            "edges": [e.model_dump() for e in all_edges],
        }

    def get_statistics(self) -> Dict[str, Any]:
        type_counts = {}
        for node in self._nodes.values():
            type_counts[node.type] = type_counts.get(node.type, 0) + 1
        return {
            "total_nodes": len(self._nodes),
            "total_edges": len(self._edges),
            "node_types": type_counts,
        }
