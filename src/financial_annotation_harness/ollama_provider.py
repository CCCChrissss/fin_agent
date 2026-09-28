"""Native Ollama adapter. No pulls, polling, repair, or implicit request retries."""
from __future__ import annotations

import copy
import time
import uuid
from urllib.parse import urlparse

import httpx

from .io_utils import canonical
from .model_client import ProviderError, Turn


def local_url(value):
    value = value or "http://127.0.0.1:11434"
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1") or parsed.username or parsed.password:
        raise ValueError("Ollama study endpoint must be local HTTP without credentials")
    return value.rstrip("/")


def request_json(client, method, path, **kwargs):
    try:
        response = client.request(method, path, **kwargs)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Expected response object")
        if data.get("error"):
            raise ProviderError("MODEL_FAILURE", "Ollama returned a model error")
        return data
    except httpx.TimeoutException as exc:
        raise ProviderError("TIMEOUT", "Ollama request timed out; not retried") from exc
    except httpx.HTTPStatusError as exc:
        kind = "MODEL_NOT_FOUND" if exc.response.status_code == 404 else "HTTP_ERROR"
        raise ProviderError(kind, f"Ollama HTTP {exc.response.status_code}; not retried") from exc
    except httpx.RequestError as exc:
        raise ProviderError("CONNECTION_ERROR", "Ollama transport failed; not retried") from exc
    except ValueError as exc:
        raise ProviderError("MALFORMED_RESPONSE", "Ollama response is not a JSON object") from exc


def inventory(base_url=None, client=None):
    """One bounded snapshot, never triggers download or generation."""
    owned = client is None
    client = client or httpx.Client(base_url=local_url(base_url), timeout=5, trust_env=False)
    try:
        return {"ollama_version": request_json(client, "GET", "/api/version")["version"],
                "models": request_json(client, "GET", "/api/tags")["models"]}
    finally:
        if owned:
            client.close()


class OllamaProvider:
    def __init__(self, settings, *, allow_live=False, http_client=None):
        if not allow_live:
            raise ValueError("Live inference disabled; explicit --live required")
        settings.require_live()
        if settings.model.provider != "ollama":
            raise ValueError("Wrong provider")
        self.settings, self.calls = settings, 0
        self.http = http_client or httpx.Client(base_url=local_url(settings.model.base_url),
            timeout=httpx.Timeout(settings.model.timeout_seconds, connect=settings.model.connect_timeout_seconds), trust_env=False)
        try:
            self.runtime = self.verify_identity()
        except Exception:
            self.http.close()
            raise
        self.deadline = None

    def verify_identity(self):
        m = self.settings.model
        snapshot = inventory(client=self.http)
        if snapshot["ollama_version"] != m.expected_ollama_version:
            raise ValueError("Ollama runtime version drift")
        matches = [r for r in snapshot["models"] if r.get("name") == m.generator_model or r.get("model") == m.generator_model]
        if len(matches) != 1:
            raise ProviderError("MODEL_NOT_FOUND", "Configured model is not installed; no download attempted")
        row = matches[0]
        if row["digest"] != m.generator_version or row["details"]["quantization_level"] != m.expected_quantization:
            raise ValueError("Ollama model digest/quantization drift")
        details = request_json(self.http, "POST", "/api/show", json={"model": m.generator_model})
        capabilities = details.get("capabilities", row.get("capabilities", []))
        if "tools" not in capabilities:
            raise ValueError("Selected Ollama model does not declare tool capability")
        if m.think not in (None, False) and "thinking" not in capabilities:
            raise ValueError("Thinking requested for a model without thinking capability")
        return {"provider": "ollama", "ollama_version": snapshot["ollama_version"],
                "model_tag": m.generator_model, "digest": row["digest"],
                "quantization": row["details"]["quantization_level"], "model_details": row["details"],
                "capabilities": capabilities, "template": details.get("template"), "model_parameters": details.get("parameters"),
                "model_info": details.get("model_info", {})}

    def begin_question(self):
        self.deadline = time.monotonic() + self.settings.model.question_timeout_seconds

    def describe_request(self, role, seed):
        m = self.settings.model
        options = {"num_ctx": m.num_ctx, "num_predict": m.max_tokens}
        for key, value in {"temperature": m.judge_temperature if role == "judge" else m.generator_temperature,
                           "top_p": m.top_p, "top_k": m.top_k, "repeat_penalty": m.repeat_penalty}.items():
            if value is not None:
                options[key] = value
        if seed is not None:
            options["seed"] = seed
        payload = {"model": m.generator_model, "stream": False, "options": options, "keep_alive": m.keep_alive}
        if m.think is not None:
            payload["think"] = m.think
        return payload

    def describe_completion_request(self, role, seed, tools):
        return self.describe_request(role, seed)

    def complete(self, messages, tools, *, role, seed):
        if role not in ("generator", "judge"):
            raise ValueError("Unknown model role")
        if self.calls >= self.settings.max_live_calls:
            raise ProviderError("CALL_BUDGET", "Local inference request budget exhausted")
        remaining = self.deadline - time.monotonic() if self.deadline else self.settings.model.timeout_seconds
        if remaining <= 0:
            raise ProviderError("TIMEOUT", "Question deadline exceeded")
        payload = self.describe_completion_request(role, seed, tools)
        converted, names = [], {}
        for original in messages:
            msg = copy.deepcopy(original)
            if msg.get("tool_calls"):
                converted_calls = []
                for call in msg["tool_calls"]:
                    import json
                    names[call["id"]] = call["function"]["name"]
                    args = call["function"]["arguments"]
                    converted_calls.append({"function": {"name": names[call["id"]],
                        "arguments": json.loads(args) if isinstance(args, str) else args}})
                msg["tool_calls"] = converted_calls
            if msg["role"] == "tool":
                msg["tool_name"] = names[msg.pop("tool_call_id")]
            converted.append(msg)
        payload["messages"] = converted
        if tools:
            payload["tools"] = tools
        self.calls += 1
        started = time.monotonic()
        data = request_json(self.http, "POST", "/api/chat", json=payload,
                            timeout=httpx.Timeout(min(remaining, self.settings.model.timeout_seconds),
                                                  connect=self.settings.model.connect_timeout_seconds))
        try:
            if data["model"] != self.settings.model.generator_model or data.get("done") is not True:
                raise ValueError("Incomplete response or wrong model")
            message = data["message"]
            content = message.get("content")
            if content is not None and not isinstance(content, str):
                raise ValueError("Invalid content")
            calls = []
            request_id = uuid.uuid4().hex
            for i, call in enumerate(message.get("tool_calls") or []):
                function = call["function"]
                if not isinstance(function["arguments"], dict) or not isinstance(function["name"], str):
                    raise ValueError("Malformed tool call")
                calls.append({"id": f"local_{request_id}_{i}", "type": "function",
                              "function": {"name": function["name"], "arguments": canonical(function["arguments"])}})
            durations = {key: data.get(key) for key in ("total_duration", "load_duration", "prompt_eval_duration", "eval_duration")}
            return Turn(content=content, tool_calls=calls, model=data["model"], request_id=request_id,
                finish_reason=data.get("done_reason", "stop"), input_tokens=data.get("prompt_eval_count"), output_tokens=data.get("eval_count"),
                runtime={**self.runtime, "request_parameters": self.describe_completion_request(role, seed, tools),
                         "wall_latency_ms": round((time.monotonic() - started) * 1000), "durations_ns": durations,
                         "thinking_present": bool(message.get("thinking")), "request_id_origin": "harness"})
        except (KeyError, TypeError, ValueError) as exc:
            diagnostic_response = copy.deepcopy(data)
            if isinstance(diagnostic_response.get("message"), dict):
                diagnostic_response["message"].pop("thinking", None)
            raise ProviderError("MALFORMED_RESPONSE", "Invalid Ollama chat response; no repair attempted",
                diagnostics={"response": diagnostic_response, "parse_error_type": type(exc).__name__,
                             "parse_error": str(exc), "role": role,
                             "request_parameters": self.describe_completion_request(role, seed, tools),
                             "wall_latency_ms": round((time.monotonic() - started) * 1000)}) from exc

    def close(self):
        self.http.close()

    def unload(self):
        """A single explicit model lifecycle request, not a completion or status poll."""
        return request_json(self.http, "POST", "/api/generate", json={"model": self.settings.model.generator_model,
                                                                    "keep_alive": 0, "stream": False})
