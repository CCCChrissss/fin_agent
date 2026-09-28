"""One authoritative config, resolved before any live request."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, model_validator

from .schemas import StrictModel


class ModelConfig(StrictModel):
    provider: Literal["fake", "openai", "ollama"] = "fake"
    base_url: str | None = None
    expected_ollama_version: str | None = None
    expected_quantization: str | None = None
    num_ctx: int = Field(default=8192, ge=1024)
    think: bool | Literal["low", "medium", "high"] | None = False
    structured_output_mode: Literal["prompt_only"] = "prompt_only"
    keep_alive: str = "5m"
    connect_timeout_seconds: float = Field(default=5, gt=0, le=60)
    question_timeout_seconds: float = Field(default=900, gt=0)
    generator_model: str = "offline-scripted"
    generator_version: str = "1"
    judge_model: str = "offline-scripted"
    judge_version: str = "1"
    generator_temperature: float | None = 0.0
    judge_temperature: float | None = 0.0
    top_p: float | None = Field(default=None, gt=0, le=1)
    top_k: int | None = Field(default=None, ge=0)
    repeat_penalty: float | None = Field(default=None, gt=0)
    max_tokens: int = Field(default=4096, ge=1)
    supports_seed: bool = False
    base_seed: int = 20260915
    timeout_seconds: float = Field(default=300.0, gt=0)


class Settings(StrictModel):
    protocol_version: Literal["1.0", "1.1"] = "1.0"
    runs_per_condition: Literal[1, 3] = 3
    conditions: list[Literal["A", "B", "C", "D"]] = Field(default_factory=lambda: ["A", "B", "C", "D"])
    max_retries: Literal[2] = 2
    language: Literal["zh", "en"] = "zh"
    split_seed: int = 20260915
    model: ModelConfig = Field(default_factory=ModelConfig)
    search_top_k: int = Field(default=12, ge=1, le=138)
    max_tool_calls_per_attempt: int = Field(default=12, ge=1, le=100)
    max_model_calls_per_attempt: int = Field(default=14, ge=1, le=100)
    # No invisible SDK retries or re-sampling on transport failure.
    transport_retries: Literal[0] = 0
    max_live_calls: int = Field(default=0, ge=0)
    selection_record: str | None = None
    review_mode: Literal["human", "ai_assisted"] = "human"
    review_record: str | None = None

    @model_validator(mode="after")
    def four_conditions(self):
        if (self.protocol_version, self.runs_per_condition) not in (("1.0", 3), ("1.1", 1)):
            raise ValueError("Run count must match the explicitly selected protocol revision")
        if self.conditions != ["A", "B", "C", "D"]:
            raise ValueError("Main protocol requires exactly A/B/C/D in that order")
        return self

    def require_live(self) -> None:
        m = self.model
        if m.provider not in ("openai", "ollama") or self.max_live_calls <= 0:
            raise ValueError("Live execution requires a real provider and a positive max_live_calls")
        for value in (m.generator_model, m.generator_version, m.judge_model, m.judge_version):
            if not value or value in ("offline-scripted", "1"):
                raise ValueError("Explicit generator/judge model and version are required for live execution")
        if m.provider == "ollama":
            if not m.expected_ollama_version or not m.expected_quantization:
                raise ValueError("Ollama runtime version and quantization must be pinned")
            if (m.generator_model, m.generator_version) != (m.judge_model, m.judge_version):
                raise ValueError("First study requires the same Generator/Judge model and digest")


def load_settings(path: Path) -> Settings:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Config must be a YAML mapping")
    raw.setdefault("model", {})
    # Environment is an explicit override, fully represented in the saved config.
    mapping = {"OPENAI_MODEL": ("generator_model", str),
               "OPENAI_MODEL_VERSION": ("generator_version", str),
               "OPENAI_JUDGE_MODEL": ("judge_model", str),
               "OPENAI_JUDGE_MODEL_VERSION": ("judge_version", str),
               "GENERATOR_TEMPERATURE": ("generator_temperature", float),
               "JUDGE_TEMPERATURE": ("judge_temperature", float),
               "MAX_TOKENS": ("max_tokens", int)}
    for env, (key, convert) in mapping.items():
        if env.startswith("OPENAI_") and raw["model"].get("provider") == "ollama":
            continue
        if os.getenv(env):
            raw["model"][key] = convert(os.environ[env])
    if os.getenv("MAX_RETRIES") and int(os.environ["MAX_RETRIES"]) != 2:
        raise ValueError("MAX_RETRIES conflicts with protocol: exactly 2")
    return Settings.model_validate(raw)


def load_rules(root: Path) -> dict:
    rules = yaml.safe_load((root / "config/rules.yaml").read_text(encoding="utf-8"))
    # These are versioned research contracts, not silently ignored tuning knobs.
    expected = {"version": "1.0", "answers": {"numeric_comparison": "exact_after_declared_formatting",
                "percent_decimal_places": 2, "source_unit_required": True, "year_calendar": "gregorian", "logic_labels": ["Yes", "No"]},
                "evidence": {"required_facts_source": "explicit_question_constraints_and_declared_operands", "gold_available_online": False,
                             "context_format": "markdown_financial_table", "selected_ids_field": "retrieved_fact_ids"},
                "evaluation": {"semantic_authority": "independent_human_review", "failed_artifact_policy": "score_terminal_artifact_keep_denominator",
                               "evidence_averaging": ["macro", "micro"], "zero_recovery_denominator": None}}
    if {k: v for k, v in rules.items() if k != "execution"} != expected:
        raise ValueError("Unsupported research rules; an explicit rule implementation/version change is required")
    execution = rules["execution"]
    if set(execution) != {"timeout_seconds", "memory_mb", "max_chars"} or not 0 < execution["timeout_seconds"] <= 10 or not 64 <= execution["memory_mb"] <= 512 or not 1 <= execution["max_chars"] <= 20000:
        raise ValueError("Invalid restricted execution limits")
    return rules
