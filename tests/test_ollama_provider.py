import json

import httpx
import pytest

from financial_annotation_harness.config import ModelConfig, Settings
from financial_annotation_harness.model_client import ProviderError
from financial_annotation_harness.ollama_provider import OllamaProvider, inventory, local_url


def local_settings():
    return Settings(model=ModelConfig(provider="ollama", generator_model="fixture:tag", judge_model="fixture:tag",
        generator_version="digest1", judge_version="digest1", expected_quantization="Q4_K_M", expected_ollama_version="0.fixture"), max_live_calls=5)


def client_for(chat, captured=None, digest="digest1", version="0.fixture"):
    def handler(request):
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": version})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "fixture:tag", "digest": digest, "details": {"quantization_level": "Q4_K_M"}}]})
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion", "tools"], "template": "fixture"})
        if captured is not None:
            captured.append(json.loads(request.content))
        return chat(request)
    return httpx.Client(base_url="http://localhost:11434", transport=httpx.MockTransport(handler))


def response(message):
    return httpx.Response(200, json={"model": "fixture:tag", "done": True, "done_reason": "stop", "message": message,
                                    "prompt_eval_count": 8, "eval_count": 4, "load_duration": 2000000})


def test_tool_roundtrip_and_runtime_parameters():
    captured = []
    c = client_for(lambda r: response({"content": "", "thinking": "private", "tool_calls": [
        {"function": {"name": "search_financial_facts", "arguments": {"query": "revenue"}}}]}), captured)
    provider = OllamaProvider(local_settings(), allow_live=True, http_client=c)
    turn = provider.complete([{"role": "user", "content": "question"}], [{"type": "function"}], role="generator", seed=7)
    call = turn.tool_calls[0]
    provider.complete([turn.message(), {"role": "tool", "tool_call_id": call["id"], "content": "{}"}], [], role="generator", seed=7)
    assert captured[1]["messages"][1]["tool_name"] == "search_financial_facts"
    assert captured[1]["messages"][0]["tool_calls"][0]["function"]["arguments"] == {"query": "revenue"}
    assert "private" not in json.dumps(captured)
    assert captured[0]["options"] == {"num_ctx": 8192, "num_predict": 4096, "temperature": 0.0, "seed": 7}
    assert "format" not in captured[0] and captured[0]["think"] is False
    assert turn.runtime["digest"] == "digest1" and turn.runtime["durations_ns"]["load_duration"] == 2000000


@pytest.mark.parametrize("status,kind", [(404, "MODEL_NOT_FOUND"), (500, "HTTP_ERROR")])
def test_http_errors_no_retry(status, kind):
    seen = []
    p = OllamaProvider(local_settings(), allow_live=True, http_client=client_for(lambda r: httpx.Response(status), seen))
    with pytest.raises(ProviderError) as exc:
        p.complete([], [], role="generator", seed=None)
    assert exc.value.kind == kind and len(seen) == 1


def test_timeout_no_retry():
    def timeout(request):
        raise httpx.ReadTimeout("simulated", request=request)
    p = OllamaProvider(local_settings(), allow_live=True, http_client=client_for(timeout))
    with pytest.raises(ProviderError) as exc:
        p.complete([], [], role="generator", seed=None)
    assert exc.value.kind == "TIMEOUT" and p.calls == 1


@pytest.mark.parametrize("data", [[], {"done": False}, {"model": "fixture:tag", "done": True, "message": {"content": 4}}, {"error": "out of memory"}])
def test_malformed_or_model_failure(data):
    p = OllamaProvider(local_settings(), allow_live=True, http_client=client_for(lambda r: httpx.Response(200, json=data)))
    with pytest.raises(ProviderError):
        p.complete([], [], role="generator", seed=None)


def test_identity_drift_and_same_judge():
    with pytest.raises(ValueError, match="drift"):
        OllamaProvider(local_settings(), allow_live=True, http_client=client_for(lambda r: response({}), digest="changed"))
    s = local_settings()
    s.model.judge_model = "stronger"
    with pytest.raises(ValueError, match="same"):
        s.require_live()


def test_deadline_and_explicit_live():
    with pytest.raises(ValueError, match="disabled"):
        OllamaProvider(local_settings())
    p = OllamaProvider(local_settings(), allow_live=True, http_client=client_for(lambda r: response({"content": "{}"})))
    p.deadline = 1
    with pytest.raises(ProviderError) as exc:
        p.complete([], [], role="generator", seed=None)
    assert exc.value.kind == "TIMEOUT" and p.calls == 0


def test_local_only_and_inventory_is_bounded():
    for url in ("http://cloud.example", "http://token@localhost:11434", "https://localhost"):
        with pytest.raises(ValueError):
            local_url(url)
    c = client_for(lambda r: pytest.fail("Inventory must not generate"))
    assert len(inventory(client=c)["models"]) == 1
