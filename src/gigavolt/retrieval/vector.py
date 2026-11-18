"""Semantic retrieval over technical documents stored in ChromaDB.

Query text is embedded by the remote embedding service
(`gigavolt.services.embedding_api`) so the RAG server does not need to load the
sentence-transformer model itself.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from functools import lru_cache

import chromadb
import httpx

from gigavolt.config import EMBEDDING_DIMENSIONS, VectorSettings, get_settings

logger = logging.getLogger(__name__)


class VectorRetriever:
    def __init__(self, settings: VectorSettings | None = None):
        self.settings = settings or get_settings().vector
        self.connect_chroma()
        # Cache per instance; identical questions skip the embedding round trip.
        self.generate_query_embedding = lru_cache(maxsize=256)(self._generate_query_embedding)

    def connect_chroma(self) -> None:
        self.client = chromadb.HttpClient(
            host=self.settings.chroma_host,
            port=self.settings.chroma_port,
        )
        self.collection = self.client.get_collection(name=self.settings.collection)
        logger.info("Connected to ChromaDB collection: %s", self.settings.collection)

    def reconnect_chroma(self) -> None:
        try:
            self.client.close()
        except Exception:  # noqa: BLE001 - best effort close
            pass
        self.connect_chroma()

    def test_connection(self) -> dict:
        return {
            "collection": self.collection.name,
            "document_count": self.collection.count(),
        }

    def _generate_query_embedding(self, query: str) -> list[float]:
        """Embed a query via the embedding API, retrying 429/5xx and network errors."""
        payload = json.dumps({"text": query}).encode("utf-8")
        attempts = 3

        for attempt in range(1, attempts + 1):
            request = urllib.request.Request(
                self.settings.embedding_api_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=15) as response:
                    result = json.loads(response.read().decode("utf-8"))

                embedding = result["embedding"]
                if len(embedding) != EMBEDDING_DIMENSIONS:
                    raise ValueError(
                        f"Expected {EMBEDDING_DIMENSIONS} dimensions, received {len(embedding)}"
                    )
                return embedding

            except urllib.error.HTTPError as error:
                retryable = error.code == 429 or error.code >= 500
                if not retryable or attempt == attempts:
                    raise RuntimeError(f"Embedding API HTTP error: {error.code}") from error
                logger.warning(
                    "Embedding API returned HTTP %s. Retry %s/%s",
                    error.code, attempt, attempts,
                )

            except urllib.error.URLError as error:
                if attempt == attempts:
                    raise RuntimeError(f"Embedding API connection failed: {error}") from error
                logger.warning("Embedding API unavailable. Retry %s/%s", attempt, attempts)

            time.sleep(0.5 * attempt)

        raise RuntimeError("Embedding generation failed.")

    def search(self, query: str, limit: int = 5) -> dict:
        """Return the nearest chunks with documents, metadata and distances."""
        query_embedding = self.generate_query_embedding(query)
        attempts = 3

        for attempt in range(1, attempts + 1):
            try:
                return self.collection.query(
                    query_embeddings=[query_embedding],
                    n_results=limit,
                    include=["documents", "metadatas", "distances"],
                )
            except (httpx.TransportError, httpx.TimeoutException):
                if attempt == attempts:
                    logger.exception("ChromaDB search failed after retries.")
                    raise
                logger.warning(
                    "ChromaDB connection interrupted. Reconnecting (%s/%s).",
                    attempt, attempts,
                )
                self.reconnect_chroma()
                time.sleep(0.5 * attempt)

        raise RuntimeError("unreachable")
