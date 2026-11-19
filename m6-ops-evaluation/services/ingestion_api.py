"""HTTP trigger for the incremental document pipeline.

    GET  /health                       -> {"status": "healthy"}
    POST /run   (header X-API-Key)     -> runs one ingestion pass, returns its summary

Only one run executes at a time (HTTP 409 if a run is already in progress).

    M6_API_KEY=... python -m gigavolt.services.ingestion_api

Environment: M6_API_KEY (required), INGESTION_API_HOST (0.0.0.0),
INGESTION_API_PORT (8002).
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from gigavolt.ingestion.documents.sync import DocumentPipeline

logger = logging.getLogger("gigavolt.ingestion_api")
run_lock = threading.Lock()


class IngestionHandler(BaseHTTPRequestHandler):
    api_key: str = ""

    def send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - http.server API
        if self.path == "/health":
            self.send_json(200, {"status": "healthy"})
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self):  # noqa: N802 - http.server API
        if self.path != "/run":
            self.send_json(404, {"error": "Not found"})
            return

        supplied = self.headers.get("X-API-Key", "")
        if not hmac.compare_digest(supplied, self.api_key):
            self.send_json(401, {"error": "Unauthorized"})
            return

        if not run_lock.acquire(blocking=False):
            self.send_json(409, {"error": "Ingestion already running"})
            return

        pipeline = None
        try:
            pipeline = DocumentPipeline(apply=True)
            self.send_json(200, {"status": "completed", "summary": pipeline.run()})
        except Exception as exc:  # noqa: BLE001 - report as 500
            logger.exception("Ingestion run failed")
            self.send_json(500, {"status": "failed", "error": str(exc)})
        finally:
            if pipeline:
                pipeline.close()
            run_lock.release()

    def log_message(self, format, *args):  # noqa: A002 - http.server API
        logger.info(format, *args)


def serve() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    api_key = os.environ.get("M6_API_KEY")
    if not api_key:
        raise RuntimeError("M6_API_KEY environment variable is required")

    IngestionHandler.api_key = api_key
    host = os.getenv("INGESTION_API_HOST", "0.0.0.0")
    port = int(os.getenv("INGESTION_API_PORT", "8002"))

    server = ThreadingHTTPServer((host, port), IngestionHandler)
    logger.info("Document ingestion API listening on %s:%s", host, port)
    server.serve_forever()


if __name__ == "__main__":
    serve()
