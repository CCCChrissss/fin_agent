"""Model boundary: scripted offline client and opt-in OpenAI adapter."""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from typing import Protocol

from .config import Settings


@dataclass
class Turn:
    content: str | None = None
    tool_calls: list[dict] = field(default_factory=list)
    model: str = "offline-scripted"
    request_id: str | None = None
    finish_reason: str = "stop"
    input_tokens: int | None = None
    output_tokens: int | None = None
    system_fingerprint: str | None = None
    runtime: dict = field(default_factory=dict)

    def message(self) -> dict:
        message = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            message["tool_calls"] = self.tool_calls
        return message


class ModelProvider(Protocol):
    def complete(self, messages: list[dict], tools: list[dict], *, role: str, seed: int | None) -> Turn: ...


ModelClient = ModelProvider  # Backward-compatible public import.


class ProviderError(RuntimeError):
    def __init__(self, kind: str, message: str, *, diagnostics: dict | None = None):
        super().__init__(message)
        self.kind = kind
        self.diagnostics = diagnostics


def create_provider(settings, *, allow_live=False):
    if settings.model.provider == "ollama":
        from .ollama_provider import OllamaProvider
        return OllamaProvider(settings, allow_live=allow_live)
    if settings.model.provider == "openai":
        return OpenAIClient(settings, allow_live=allow_live)
    raise ValueError("Use ScriptedClient explicitly for offline tests")


class ScriptedClient:
    """No network. Tests control the exact sequence, including malformed outputs."""
    def __init__(self, turns: list[Turn]):
        self.turns = copy.deepcopy(turns)
        self.requests = []

    def complete(self, messages, tools, *, role, seed):
        self.requests.append(copy.deepcopy({"messages": messages, "tools": tools, "role": role, "seed": seed}))
        if not self.turns:
            raise RuntimeError("Scripted response sequence exhausted")
        return self.turns.pop(0)


class OpenAIClient:
    def __init__(self, settings: Settings, *, allow_live: bool = False, sdk_client=None):
        if not allow_live:
            raise ValueError("Live API is disabled; explicit --live is required")
        settings.require_live()
        self.settings = settings
        self.calls = 0
        if sdk_client is None:
            if not os.getenv("OPENAI_API_KEY"):
                raise ValueError("OPENAI_API_KEY is not configured")
            from openai import OpenAI
            # Disable SDK retries; do not invisibly re-sample after uncertain delivery.
            sdk_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], max_retries=0,
                                timeout=settings.model.timeout_seconds, base_url=settings.model.base_url)
        self.sdk = sdk_client

    def complete(self, messages, tools, *, role, seed):
        if self.calls >= self.settings.max_live_calls:
            raise RuntimeError("Explicit live API call budget exhausted")
        self.calls += 1
        m = self.settings.model
        params = {"model": m.judge_model if role == "judge" else m.generator_model,
                  "messages": messages, "temperature": m.judge_temperature if role == "judge" else m.generator_temperature,
                  "max_completion_tokens": m.max_tokens, "store": False}
        if params["temperature"] is None:
            params.pop("temperature")
        if seed is not None:
            params["seed"] = seed
        if tools:
            params.update(tools=tools, parallel_tool_calls=False)
        # No provider-side schema repair/enforcement advantage for any condition.
        response = self.sdk.chat.completions.create(**params)
        choice = response.choices[0]
        message = choice.message
        expected_version = m.judge_version if role == "judge" else m.generator_version
        if response.model != expected_version:
            raise ValueError(f"Provider model version drift: expected {expected_version}, received {response.model}")
        return Turn(content=message.content,
                    tool_calls=[t.model_dump(exclude_none=True) for t in message.tool_calls or []],
                    model=response.model, request_id=getattr(response, "_request_id", None),
                    finish_reason=choice.finish_reason,
                    input_tokens=response.usage.prompt_tokens if response.usage else None,
                    output_tokens=response.usage.completion_tokens if response.usage else None,
                    system_fingerprint=getattr(response, "system_fingerprint", None))
