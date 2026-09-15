"""Development-only Condition B scheduling; no Gold import or online scoring."""
from __future__ import annotations

from pathlib import Path
import time
from typing import Literal

import yaml
from pydantic import Field, model_validator

from .config import Settings
from .io_utils import digest, read_json, timestamp, write_new_json
from .model_client import create_provider
from .runner import AnnotationRunner
from .schemas import QuestionInput, StrictModel
from .trace import TraceStore


class Candidate(StrictModel):
    candidate_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    model_tag: str
    digest: str | None = None
    quantization: str | None = None
    think: bool | Literal["low", "medium", "high"] | None = False


class ScreeningConfig(StrictModel):
    experiment_kind: Literal["screening"] = "screening"
    partition: Literal["development"] = "development"
    condition: Literal["B"] = "B"
    stage: Literal["initial", "tie_break"] = "initial"
    run_indices: list[int] = Field(default_factory=lambda: [1])
    candidates: list[Candidate]
    settings: Settings = Field(default_factory=Settings)
    concurrency: Literal[1] = 1
    warmup_requests: Literal[0, 1] = 1
    unload_between_models: Literal[True] = True
    max_wall_seconds: float = Field(default=14400, gt=0)
    order_seed: int = 20260915
    parent_experiment: str | None = None
    tie_break_reason: str | None = None

    @model_validator(mode="after")
    def study_contract(self):
        count, runs = (2, [1]) if self.stage == "initial" else (2, [2, 3])
        if len(self.candidates) != count or self.run_indices != runs:
            raise ValueError("Initial requires 2 models/run 1; tie-break requires 2 models/runs 2,3")
        if len({c.candidate_id for c in self.candidates}) != count or len({c.model_tag for c in self.candidates}) != count:
            raise ValueError("Candidate IDs and model tags must be unique")
        if self.settings.model.provider != "ollama":
            raise ValueError("Local screening requires Ollama")
        if self.stage == "tie_break" and (not self.parent_experiment or not self.tie_break_reason):
            raise ValueError("Tie-break requires parent experiment and human reason")
        return self

    def candidate_settings(self, candidate):
        settings = self.settings.model_copy(deep=True)
        m = settings.model
        m.generator_model = m.judge_model = candidate.model_tag
        m.generator_version = m.judge_version = candidate.digest or ""
        m.expected_quantization = candidate.quantization
        m.think = candidate.think
        return settings


def load_screening(path):
    return ScreeningConfig.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def screening_schedule(config, split):
    ids = split["development"]
    if len(ids) != 12 or len(set(ids)) != 12 or set(ids) & set(split["test"]):
        raise ValueError("Screening requires the fixed 12-question Development split")
    if config.settings.split_seed != split["seed"]:
        raise ValueError("Screening split seed mismatch")
    ordered = sorted(ids, key=lambda q: digest([config.order_seed, q]))
    return [{"candidate_id": c.candidate_id, "run_index": r, "condition": "B", "question_id": q}
            for c in config.candidates for r in config.run_indices for q in ordered]


def validate_parent(config, root, provenance):
    if config.stage != "tie_break":
        return
    parent_path = (root / config.parent_experiment).resolve(strict=True)
    if not parent_path.is_relative_to(root):
        raise ValueError("Parent experiment must be inside project")
    parent = read_json(parent_path / "manifest.json")
    old = ScreeningConfig.model_validate(parent["screening_config"])
    if old.stage != "initial" or old.settings != config.settings or old.order_seed != config.order_seed or old.warmup_requests != config.warmup_requests:
        raise ValueError("Tie-break controls differ from initial screening")
    for key, value in provenance.items():
        if parent.get(key) != value:
            raise ValueError(f"Tie-break changed {key}")
    if any(c not in old.candidates for c in config.candidates):
        raise ValueError("Tie-break candidates must match initial pinned profiles")


def run_screening(config, split, questions, repo, rules, prompts, output, provenance, environment,
                  *, resume=False, provider_factory=create_provider):
    schedule = screening_schedule(config, split)
    if set(questions) != set(split["development"]):
        raise ValueError("Runner accepts only Development inputs")
    for candidate in config.candidates:
        config.candidate_settings(candidate).require_live()
    manifest = {"experiment_kind": "screening", "mode": "live", "screening_config": config.model_dump(),
                "expected_runs": schedule, **provenance}
    if output.exists():
        if not resume:
            raise ValueError("Screening exists; use --resume with identical controls")
        old = read_json(output / "manifest.json")
        if any(old.get(k) != v for k, v in manifest.items()) or old["environment"] != environment:
            raise ValueError("Cannot resume changed screening/environment")
    else:
        if resume:
            raise ValueError("Cannot resume nonexistent screening")
        output.mkdir(parents=True)
        write_new_json(output / "manifest.json", {**manifest, "environment": environment, "created_at": timestamp()})
    calls_total = 0
    started = time.monotonic()
    # One outer lock prevents competing candidates from running on the same study.
    with TraceStore(output) as journal:
        prior = journal.read("events")
        calls_total += sum(e["event"] == "warmup_request" for e in prior)
        for c in config.candidates:
            for r in config.run_indices:
                store = TraceStore(output / c.candidate_id / f"run_{r:02d}" / "B")
                calls_total += sum(e["event"] == "generator_request" for e in store.read("events"))
        for candidate in config.candidates:
            if time.monotonic() - started >= config.max_wall_seconds:
                raise ValueError("Screening wall-time budget exhausted; no automatic continuation")
            settings = config.candidate_settings(candidate)
            provider = provider_factory(settings, allow_live=True)
            provider.calls = calls_total
            try:
                prior_warm = [e for e in prior if e.get("candidate_id") == candidate.candidate_id and e["event"].startswith("warmup_")]
                if config.warmup_requests and not prior_warm:
                    warmup_messages = [{"role": "user", "content": "Return the JSON object {}."}]
                    warmup_seed = settings.model.base_seed if settings.model.supports_seed else None
                    journal.append("events", {"event": "warmup_request", "candidate_id": candidate.candidate_id,
                        "messages": warmup_messages, "seed": warmup_seed, "model_config": settings.model.model_dump()})
                    turn = provider.complete(warmup_messages, [], role="generator", seed=warmup_seed)
                    journal.append("events", {"event": "warmup_response", "candidate_id": candidate.candidate_id, "runtime": turn.runtime})
                elif config.warmup_requests and not any(e["event"] == "warmup_response" for e in prior_warm):
                    raise ValueError("Interrupted warmup: no automatic resampling; start a separately documented study")
                for run in config.run_indices:
                    with TraceStore(output / candidate.candidate_id / f"run_{run:02d}" / "B") as store:
                        runner = AnnotationRunner(settings, repo, rules, prompts, provider, store, trace_context={
                            "experiment_kind": "screening", "candidate_id": candidate.candidate_id,
                            "screening_stage": config.stage, "config_hash": digest(config.model_dump()), "environment_hash": digest(environment)})
                        completed_ids = {f["question_id"] for f in store.read("finals")}
                        for row in schedule:
                            if row["candidate_id"] == candidate.candidate_id and row["run_index"] == run:
                                if row["question_id"] in completed_ids:
                                    continue
                                if time.monotonic() - started >= config.max_wall_seconds:
                                    raise ValueError("Screening wall-time budget exhausted; records retained")
                                runner.run_question(questions[row["question_id"]], source_question_id=row["question_id"],
                                    condition="B", run_index=run, experiment_id=f"{output.name}/{candidate.candidate_id}")
                                last = store.read("attempts")[-1]
                                if last.get("runtime_error_type") in ("TIMEOUT", "CONNECTION_ERROR", "CALL_BUDGET"):
                                    raise ValueError("Screening stopped after uncertain inference/budget failure; explicit resume required")
                if hasattr(provider, "verify_identity"):
                    provider.verify_identity()
                journal.append("events", {"event": "candidate_complete", "candidate_id": candidate.candidate_id,
                                          "runtime": getattr(provider, "runtime", {})})
                if hasattr(provider, "unload"):
                    journal.append("events", {"event": "unload_request", "candidate_id": candidate.candidate_id})
                    provider.unload()
                    journal.append("events", {"event": "unload_complete", "candidate_id": candidate.candidate_id})
            finally:
                calls_total = provider.calls
                if hasattr(provider, "close"):
                    provider.close()
    return {"question_runs": len(schedule), "requests_attempted": calls_total, "output": str(output), "winner": None}
