import json
import logging
import os
from pathlib import Path
from typing import List

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

    def __init__(self, model: str | None = None, api_key: str | None = None):
        from openai import OpenAI

        self._model = model or os.getenv(
            "OPENROUTER_EMBED_MODEL", "nvidia/nemotron-3-embed-1b-20260716:free"
        )
        self._client = OpenAI(
            api_key=api_key or Config.OPENROUTER_API_KEY,
            base_url=self.BASE_URL,
        )

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        response = self._client.embeddings.create(model=self._model, input=texts)
        return [item.embedding for item in response.data]

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]


class SelfLearningMemory:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path
        self.embeddings = OpenRouterEmbeddings()
        self.index = None
        self.knowledge = self.load_initial_knowledge()
        self._load_or_init_index()

    def load_initial_knowledge(self) -> List[str]:
        """Preload pentest knowledge"""
        # decode/memory/self_learning.py -> repo root is three parents up
        initial_path = Path(__file__).resolve().parent.parent.parent / "data/initial_knowledge.json"
        with open(initial_path) as f:
            data = json.load(f)
        return data["exploits"] + data["techniques"]

    def _load_or_init_index(self):
        index_path = self.memory_path / "hack_memory.index"
        if index_path.exists():
            self.index = faiss.read_index(str(index_path))
            with open(self.memory_path / "vectors.npy", "rb") as f:
                self.vectors = np.load(f)
        else:
            self._build_initial_index()

    def _build_initial_index(self):
        texts = self.knowledge
        try:
            embeddings = self.embeddings.embed_documents(texts)
        except Exception as e:
            logging.warning("Failed to build initial index (embedding API error): %s", e)
            self.index = faiss.IndexFlatL2(768)
            return
        self.vectors = np.array(embeddings).astype("float32")
        d = self.vectors.shape[1] if self.vectors.size > 0 else 768
        self.index = faiss.IndexFlatL2(d)
        if self.vectors.size > 0:
            self.index.add(self.vectors)
        self.save()

    def add_experience(self, query: str, action: str, result: str, success: bool):
        """Self-learning: store successful exploits"""
        experience = (
            f"Query: {query} | Action: {action} | Result: {result} | Success: {success}"
        )
        embedding = (
            np.array(self.embeddings.embed_query(experience))
            .astype("float32")
            .reshape(1, -1)
        )
        self.index.add(embedding)
        self.vectors = np.vstack([self.vectors, embedding])
        self.save()

    def retrieve_relevant(self, query: str, k: int = 5) -> List[str]:
        try:
            query_emb = (
                np.array(self.embeddings.embed_query(query))
                .astype("float32")
                .reshape(1, -1)
            )
        except Exception as e:
            logging.warning("Embedding API error in retrieve_relevant: %s", e)
            return []
        if self.index is None or self.index.ntotal == 0:
            return []
        try:
            distances, indices = self.index.search(query_emb, k)
        except Exception as e:
            logging.warning("FAISS search error: %s", e)
            return []
        return [self.knowledge[i] for i in indices[0] if i < len(self.knowledge)]

    def save(self):
        faiss.write_index(self.index, str(self.memory_path / "hack_memory.index"))
        np.save(self.memory_path / "vectors.npy", self.vectors)
