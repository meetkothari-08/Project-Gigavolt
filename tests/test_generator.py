import io
import json

from gigavolt.config import OllamaSettings
from gigavolt.rag import generator as generator_module
from gigavolt.rag.generator import AnswerGenerator
from gigavolt.rag.provenance import FALLBACK_MARKER

CONTEXT = {
    "documents": [{"source_id": f"doc-{i}", "content": "x" * 1000} for i in range(5)],
    "mariadb": [{"source_id": f"dispatch:D-{i}", "record": {"id": i}} for i in range(4)],
    "mongodb": [{"source_id": "telemetry:t1", "record": {"temperature_c": 44.0,
                                                          "fault_code": "ERR_THM_204"}}],
}


def make_generator():
    return AnswerGenerator(OllamaSettings(base_url="http://ollama.test", model="phi:test",
                                          timeout=5))


def test_prepare_context_respects_evidence_budget():
    evidence = make_generator().prepare_context(CONTEXT)
    databases = [item["database"] for item in evidence]
    assert databases.count("ChromaDB") == 3
    assert databases.count("MariaDB") == 2
    assert databases.count("MongoDB") == 1
    assert all(len(item["evidence"]) <= 300 for item in evidence if item["database"] == "ChromaDB")
    telemetry = evidence[-1]["evidence"]
    assert telemetry["temperature_c"] == 44.0 and telemetry["fault_code"] == "ERR_THM_204"


def test_payload_is_deterministic_and_bounded():
    payload = make_generator().build_payload("Why?", [])
    assert payload["options"] == {"temperature": 0, "num_ctx": 1024, "num_predict": 80}
    assert payload["stream"] is False
    assert "Why?" in payload["prompt"]


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_urlopen(answer):
    def _urlopen(request, timeout):
        body = {"response": answer, "prompt_eval_count": 10, "eval_count": 5,
                "prompt_eval_duration": 2_000_000_000, "eval_duration": 1_000_000_000}
        return FakeResponse(json.dumps(body).encode())
    return _urlopen


def test_fallback_source_list_appended_when_model_cites_nothing(monkeypatch):
    monkeypatch.setattr(generator_module.urllib.request, "urlopen", fake_urlopen("No idea."))
    result = make_generator().generate("Why?", CONTEXT)
    assert FALLBACK_MARKER in result["answer"]
    assert "[doc-0]" in result["answer"]
    assert result["prompt_eval_seconds"] == 2.0


def test_no_fallback_when_model_cites_a_source(monkeypatch):
    monkeypatch.setattr(generator_module.urllib.request, "urlopen",
                        fake_urlopen("Overheated [telemetry:t1]."))
    result = make_generator().generate("Why?", CONTEXT)
    assert FALLBACK_MARKER not in result["answer"]
