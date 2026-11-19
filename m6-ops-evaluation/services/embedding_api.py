"""Query-embedding microservice.

Loads ``intfloat/e5-small-v2`` once and serves normalized 384-dimensional
query embeddings, so the RAG server never has to load the model itself.

    GET  /health  -> {"status": "healthy", "model": ..., "dimensions": 384}
    POST /embed   {"text": "..."} -> {"embedding": [...], "dimensions": 384}

    python -m gigavolt.services.embedding_api

Environment: EMBEDDING_API_HOST (default 0.0.0.0), EMBEDDING_API_PORT (8001).
"""

from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from gigavolt.config import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL

MAX_REQUEST_BYTES = 100_000

logger = logging.getLogger("gigavolt.embedding_api")


class EmbeddingHandler(BaseHTTPRequestHandler):
    model = None  # set by serve()

    def send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - http.server API
        if self.path == "/health":
            self.send_json(200, {
                "status": "healthy",
                "model": EMBEDDING_MODEL,
                "dimensions": EMBEDDING_DIMENSIONS,
            })
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self):  # noqa: N802 - http.server API
        if self.path != "/embed":
            self.send_json(404, {"error": "Not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0 or length > MAX_REQUEST_BYTES:
                self.send_json(400, {"error": "Invalid request size"})
                return

            data = json.loads(self.rfile.read(length))
            text = str(data.get("text", "")).strip()
            if not text:
                self.send_json(400, {"error": "Text is required"})
                return

            # E5 expects the "query: " prefix for search queries.
            embedding = self.model.encode("query: " + text, normalize_embeddings=True).tolist()
            self.send_json(200, {
                "embedding": embedding,
                "dimensions": len(embedding),
                "model": EMBEDDING_MODEL,
            })
        except json.JSONDecodeError:
            self.send_json(400, {"error": "Request body must be JSON"})
        except Exception as exc:  # noqa: BLE001 - report as 500
            logger.exception("Embedding request failed")
            self.send_json(500, {"error": str(exc)})

    def log_message(self, format, *args):  # noqa: A002 - http.server API
        logger.info("%s - %s", self.address_string(), format % args)


def serve() -> None:
    from sentence_transformers import SentenceTransformer

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    host = os.getenv("EMBEDDING_API_HOST", "0.0.0.0")
    port = int(os.getenv("EMBEDDING_API_PORT", "8001"))

    logger.info("Loading embedding model: %s", EMBEDDING_MODEL)
    EmbeddingHandler.model = SentenceTransformer(EMBEDDING_MODEL, device="cpu")

    server = ThreadingHTTPServer((host, port), EmbeddingHandler)
    logger.info("Embedding API listening on %s:%s", host, port)
    server.serve_forever()


if __name__ == "__main__":
    serve()
