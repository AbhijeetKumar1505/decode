import json
import logging
import os
from pathlib import Path
from typing import Any

import faiss
import numpy as np

from ..config import Config


class OpenRouterEmbeddings:
    """Embeddings via OpenRouter's OpenAI-compatible ``/embeddings`` endpoint.

    Exposes the ``embed_documents`` / ``embed_query`` interface the memory index
    relies on. The model defaults to a free OpenRouter embedding model and can be
    overridden with ``OPENROUTER_EMBED_MODEL``.
    """

    BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        from openai import OpenAI

        self._model = model or os.getenv(
            "OPENROUTER_EMBED_MODEL", "nvidia/nemotron-3-embed-1b-20260716:free"
        )
        self._client = OpenAI(
            api_key=api_key or Config.OPENROUTER_API_KEY,
            base_url=self.BASE_URL,
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(model=self._model, input=texts)
        return [item.embedding for item in response.data]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class SelfLearningMemory:
    """Opt-in, project-bound semantic observations with an atomic local snapshot."""

    def __init__(
        self,
        memory_path: Path,
        *,
        project_id: str | None = None,
        embeddings: Any = None,
        initial_knowledge: list[str] | None = None,
    ) -> None:
        self.memory_path = memory_path
        self.project_id = project_id
        self.embeddings = embeddings
        self.index = None
        self.vectors = np.empty((0, 0), dtype="float32")
        self.knowledge: list[str] = []
        if embeddings is not None:
            if not project_id or not project_id.strip():
                raise ValueError("semantic memory requires a project")
            self._load_or_init_index(initial_knowledge or [])

    @property
    def _snapshot_path(self) -> Path:
        return self.memory_path / "semantic_memory.npz"

    @property
    def _embedding_id(self) -> str:
        return str(getattr(self.embeddings, "_model", type(self.embeddings).__name__))

    def load_initial_knowledge(self) -> list[str]:
        initial_path = (
            Path(__file__).resolve().parents[3] / "data/initial_knowledge.json"
        )
        if not initial_path.exists():
            return []
        data = json.loads(initial_path.read_text(encoding="utf-8"))
        return data["exploits"] + data["techniques"]

    def _load_or_init_index(self, initial_knowledge: list[str]) -> None:
        if self._snapshot_path.exists():
            with np.load(self._snapshot_path, allow_pickle=False) as snapshot:
                if str(snapshot["project_id"]) != self.project_id:
                    raise ValueError("semantic snapshot belongs to another project")
                if str(snapshot["embedding_id"]) != self._embedding_id:
                    raise ValueError(
                        "semantic snapshot uses a different embedding model"
                    )
                knowledge = snapshot["knowledge"].tolist()
                vectors = snapshot["vectors"]
            if not isinstance(knowledge, list) or not all(
                isinstance(item, str) for item in knowledge
            ):
                raise ValueError("invalid semantic snapshot text")
            self._replace(knowledge, vectors, persist=False)
        elif initial_knowledge:
            self._check_text(initial_knowledge)
            vectors = self.embeddings.embed_documents(initial_knowledge)
            self._replace(initial_knowledge, vectors)

    def _check_text(self, texts: list[str]) -> None:
        from ..runtime import redact_sensitive

        if any(redact_sensitive(text) != text for text in texts):
            raise ValueError("sensitive material cannot enter semantic memory")

    def _replace(
        self, knowledge: list[str], vectors: Any, *, persist: bool = True
    ) -> None:
        vectors = np.asarray(vectors, dtype="float32")
        if (
            vectors.ndim != 2
            or len(vectors) != len(knowledge)
            or not np.isfinite(vectors).all()
        ):
            raise ValueError("invalid semantic vectors")
        index = None
        if vectors.shape[1]:
            index = faiss.IndexFlatL2(vectors.shape[1])
            index.add(vectors)
        elif knowledge:
            raise ValueError("semantic vectors must have dimensions")
        if persist:
            self._save_snapshot(knowledge, vectors)
        self.knowledge = list(knowledge)
        self.vectors = vectors
        self.index = index

    def add_experience(
        self,
        query: str,
        action: str,
        result: str,
        success: bool,
        *,
        sensitive: bool = False,
    ) -> None:
        if self.embeddings is None:
            raise ValueError("semantic embeddings are not configured")
        if sensitive:
            raise ValueError("sensitive material cannot enter semantic memory")
        experience = (
            f"Query: {query} | Action: {action} | Result: {result} | Success: {success}"
        )
        self._check_text([experience])
        embedding = np.asarray(
            self.embeddings.embed_query(experience), dtype="float32"
        ).reshape(1, -1)
        vectors = np.vstack([self.vectors, embedding]) if self.knowledge else embedding
        self._replace([*self.knowledge, experience], vectors)

    def retrieve_relevant(self, query: str, k: int = 5) -> list[str]:
        if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= 100:
            raise ValueError("semantic result limit must be between 1 and 100")
        if (
            not query.strip()
            or self.embeddings is None
            or self.index is None
            or self.index.ntotal == 0
        ):
            return []
        self._check_text([query])
        try:
            vector = np.asarray(
                self.embeddings.embed_query(query), dtype="float32"
            ).reshape(1, -1)
            if vector.shape[1] != self.index.d or not np.isfinite(vector).all():
                raise ValueError("invalid query embedding")
            _, indices = self.index.search(vector, min(k, self.index.ntotal))
        except Exception:
            logging.warning("Optional semantic retrieval unavailable")
            return []
        return [self.knowledge[i] for i in indices[0] if 0 <= i < len(self.knowledge)]

    def _save_snapshot(self, knowledge: list[str], vectors: np.ndarray) -> None:
        import tempfile

        self.memory_path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=self.memory_path, suffix=".npz", delete=False
        ) as stream:
            temporary = Path(stream.name)
            try:
                np.savez(
                    stream,
                    knowledge=np.asarray(knowledge, dtype=str),
                    vectors=vectors,
                    project_id=self.project_id,
                    embedding_id=self._embedding_id,
                )
                stream.flush()
                os.fsync(stream.fileno())
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            os.replace(temporary, self._snapshot_path)
        finally:
            temporary.unlink(missing_ok=True)

    def save(self) -> None:
        if self.embeddings is None:
            raise ValueError("semantic embeddings are not configured")
        self._save_snapshot(self.knowledge, self.vectors)

    def clear(self) -> None:
        if self.embeddings is not None:
            self._replace([], np.empty((0, 0), dtype="float32"))
