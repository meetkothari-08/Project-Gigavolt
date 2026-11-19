"""Grounded answer generation with a local LLM served by Ollama."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from gigavolt.config import OllamaSettings, get_settings
from gigavolt.rag.prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from gigavolt.rag.provenance import FALLBACK_MARKER

# Evidence budget per source. Phi runs with a 1,024-token context window, so
# the prompt is kept small: three document excerpts, two relational records
# and three telemetry readings.
MAX_DOCUMENTS = 3
MAX_MARIADB_RECORDS = 2
MAX_MONGODB_RECORDS = 3
DOCUMENT_EXCERPT_CHARS = 300


class AnswerGenerator:
    """Builds a compact evidence block and asks Ollama for a cited answer."""

    def __init__(self, settings: OllamaSettings | None = None):
        self.settings = settings or get_settings().ollama
        self.model = self.settings.model

    @staticmethod
    def prepare_context(retrieved_context: dict) -> list[dict]:
        """Flatten retrieved items into prompt evidence, preserving source IDs."""
        evidence: list[dict] = []

        for item in retrieved_context.get("documents", [])[:MAX_DOCUMENTS]:
            evidence.append({
                "source_id": item.get("source_id"),
                "database": "ChromaDB",
                "evidence": str(item.get("content", ""))[:DOCUMENT_EXCERPT_CHARS],
            })

        for item in retrieved_context.get("mariadb", [])[:MAX_MARIADB_RECORDS]:
            evidence.append({
                "source_id": item.get("source_id"),
                "database": "MariaDB",
                "evidence": item.get("record", {}),
            })

        for item in retrieved_context.get("mongodb", [])[:MAX_MONGODB_RECORDS]:
            record = item.get("record", {})
            evidence.append({
                "source_id": item.get("source_id"),
                "database": "MongoDB",
                "evidence": {
                    key: record.get(key)
                    for key in (
                        "equipment_id", "model", "timestamp", "status",
                        "fault_code", "severity", "temperature_c",
                        "voltage_v", "current_a", "soc_percent",
                        "voltage_delta_mv", "flagged_components", "notes",
                    )
                },
            })

        return evidence

    def build_payload(self, question: str, evidence: list[dict]) -> dict:
        context = json.dumps(evidence, ensure_ascii=False, default=str)
        return {
            "model": self.model,
            "system": SYSTEM_PROMPT,
            "prompt": USER_PROMPT_TEMPLATE.format(question=question, context=context),
            "stream": False,
            "keep_alive": "10m",
            "options": {
                "temperature": 0,
                "num_ctx": 1024,
                "num_predict": 80,
            },
        }

    def generate(self, question: str, retrieved_context: dict) -> dict:
        """Generate an answer; append a source list if the model cited nothing."""
        evidence = self.prepare_context(retrieved_context)
        payload = self.build_payload(question, evidence)

        request = urllib.request.Request(
            f"{self.settings.base_url.rstrip('/')}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        start = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.settings.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama HTTP error {error.code}: {details}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"Could not connect to Ollama: {error}") from error
        except TimeoutError as error:
            raise RuntimeError(
                f"Ollama timed out after {self.settings.timeout} seconds."
            ) from error

        elapsed = round(time.perf_counter() - start, 2)
        answer = result.get("response", "").strip()
        if not answer:
            raise RuntimeError("Ollama returned an empty answer.")

        source_ids = [item["source_id"] for item in evidence if item.get("source_id")]
        cited = [sid for sid in source_ids if f"[{sid}]" in answer]

        # If the model cited nothing, list what it was given. This is a
        # transparency aid only; provenance scoring excludes it from the
        # claim-level (model_citations_*) metrics.
        if not cited and source_ids:
            answer += f"\n\n{FALLBACK_MARKER} " + ", ".join(f"[{sid}]" for sid in source_ids)

        return {
            "answer": answer,
            "model": self.model,
            "generation_seconds": elapsed,
            "prompt_tokens": result.get("prompt_eval_count"),
            "generated_tokens": result.get("eval_count"),
            "prompt_eval_seconds": round(result.get("prompt_eval_duration", 0) / 1e9, 2),
            "token_generation_seconds": round(result.get("eval_duration", 0) / 1e9, 2),
        }
