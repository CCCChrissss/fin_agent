from types import SimpleNamespace

import pytest

from financial_annotation_harness.config import ModelConfig, Settings
from financial_annotation_harness.model_client import OpenAIClient


def settings():
    return Settings(model=ModelConfig(provider="openai", generator_model="model-snapshot", generator_version="model-snapshot",
                                     judge_model="judge-snapshot", judge_version="judge-snapshot"), max_live_calls=2)


class FakeSDK:
    def __init__(self):
        self.chat = SimpleNamespace(completions=self)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(model=kwargs["model"], choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="{}", tool_calls=[]))],
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=3), _request_id="fixture-request", system_fingerprint="fixture")


def test_explicit_provider_parameters_and_budget():
    sdk = FakeSDK()
    with pytest.raises(ValueError, match="disabled"):
        OpenAIClient(settings(), sdk_client=sdk)
    client = OpenAIClient(settings(), allow_live=True, sdk_client=sdk)
    result = client.complete([{"role": "user", "content": "question"}], [], role="generator", seed=123)
    assert result.input_tokens == 10 and result.output_tokens == 3
    assert sdk.requests[0]["max_completion_tokens"] == 4096
    assert sdk.requests[0]["temperature"] == 0.0
    assert sdk.requests[0]["store"] is False
    assert sdk.requests[0]["seed"] == 123
    client.complete([], [], role="judge", seed=None)
    assert sdk.requests[1]["model"] == "judge-snapshot" and "seed" not in sdk.requests[1]
    with pytest.raises(RuntimeError, match="budget"):
        client.complete([], [], role="generator", seed=None)
    assert len(sdk.requests) == 2


def test_provider_snapshot_drift_rejected():
    s = settings()
    s.model.generator_version = "different-snapshot"
    client = OpenAIClient(s, allow_live=True, sdk_client=FakeSDK())
    with pytest.raises(ValueError, match="drift"):
        client.complete([], [], role="generator", seed=None)

