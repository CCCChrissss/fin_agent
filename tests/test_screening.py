import pytest

from financial_annotation_harness.config import ModelConfig, Settings
from financial_annotation_harness.model_client import ScriptedClient, Turn
from financial_annotation_harness.screening import Candidate, ScreeningConfig, run_screening, screening_schedule
from financial_annotation_harness.trace import TraceStore


def screening_config():
    return ScreeningConfig(candidates=[Candidate(candidate_id=f"m{i}", model_tag=f"fixture{i}:tag", digest=f"d{i}", quantization="Q4") for i in range(2)],
        warmup_requests=0, settings=Settings(model=ModelConfig(provider="ollama", expected_ollama_version="v"), max_live_calls=100))


def split_fixture():
    return {"development": [f"dev{i}" for i in range(12)], "test": [f"test{i}" for i in range(48)], "seed": 20260915}


def test_schedule_and_tiebreak():
    config, split = screening_config(), split_fixture()
    assert len(screening_schedule(config, split)) == 24
    with pytest.raises(ValueError, match="requires 2 models"):
        ScreeningConfig.model_validate({**config.model_dump(), "candidates": [*config.model_dump()["candidates"],
            {"candidate_id": "extra", "model_tag": "extra:tag"}]})
    raw = config.model_dump()
    raw.update(stage="tie_break", candidates=raw["candidates"][:2], run_indices=[2, 3], parent_experiment="parent", tie_break_reason="one item gap")
    assert len(screening_schedule(ScreeningConfig.model_validate(raw), split)) == 48
    for update in ({"condition": "D"}, {"partition": "test"}, {"run_indices": [1, 2]}, {"concurrency": 2}):
        with pytest.raises(ValueError):
            ScreeningConfig.model_validate({**config.model_dump(), **update})
    split["development"][0] = "test0"
    with pytest.raises(ValueError):
        screening_schedule(config, split)


class FakeProvider(ScriptedClient):
    def __init__(self, turns):
        super().__init__(turns)
        self.calls = 0
    def complete(self, *args, **kwargs):
        self.calls += 1
        return super().complete(*args, **kwargs)


def test_b_only_runner_and_resume(tmp_path, specimen, rules, prompts, monkeypatch):
    repo, q, *_ = specimen
    config, split = screening_config(), split_fixture()
    qs = {i: q.model_copy(update={"question_id": f"neutral_{i}"}) for i in split["development"]}
    def forbidden(*args, **kwargs):
        pytest.fail("Screening B must not use validators")
    monkeypatch.setattr("financial_annotation_harness.runner.validate_all", forbidden)
    providers = []
    def factory(*args, **kwargs):
        p = FakeProvider([Turn(content="{broken") for _ in range(12)])
        providers.append(p)
        return p
    out = tmp_path / "screen"
    report = run_screening(config, split, qs, repo, rules, prompts, out, {}, {}, provider_factory=factory)
    assert report["question_runs"] == 24 and report["requests_attempted"] == 24
    assert len(providers) == 2
    assert all(len(p.requests) == 12 for p in providers)
    for c in config.candidates:
        attempts = TraceStore(out / c.candidate_id / "run_01/B").read("attempts")
        assert len(attempts) == 12 and all(a["attempt"] == 1 and not a["validator_results"] and a["judge_result"] is None for a in attempts)
    run_screening(config, split, qs, repo, rules, prompts, out, {}, {}, resume=True, provider_factory=factory)
    assert len(providers) == 4 and all(not p.requests for p in providers[2:])
    with pytest.raises(ValueError, match="only Development"):
        run_screening(config, split, {**qs, "test0": q}, repo, rules, prompts, tmp_path / "bad", {}, {}, provider_factory=factory)


def test_timeout_stops_new_questions_and_preserves_failure(tmp_path, specimen, rules, prompts):
    from financial_annotation_harness.model_client import ProviderError
    repo, q, *_ = specimen
    config, split = screening_config(), split_fixture()
    questions = {qid: q for qid in split["development"]}
    class TimeoutProvider(FakeProvider):
        def complete(self, *args, **kwargs):
            self.calls += 1
            raise ProviderError("TIMEOUT", "fixture timeout")
    out = tmp_path / "interrupted"
    with pytest.raises(ValueError, match="stopped"):
        run_screening(config, split, questions, repo, rules, prompts, out, {}, {}, provider_factory=lambda *a, **k: TimeoutProvider([]))
    store = TraceStore(out / "m0/run_01/B")
    assert len(store.read("attempts")) == len(store.read("finals")) == 1
    assert store.read("attempts")[0]["runtime_error_type"] == "TIMEOUT"


def test_tiebreak_parent_control_drift_rejected(tmp_path):
    from financial_annotation_harness.screening import validate_parent
    from financial_annotation_harness.io_utils import write_new_json
    original = screening_config()
    write_new_json(tmp_path / "first/manifest.json", {"screening_config": original.model_dump(), "source_manifest_hash": "source"})
    raw = original.model_dump()
    raw.update(stage="tie_break", candidates=raw["candidates"][:2], run_indices=[2, 3], parent_experiment="first", tie_break_reason="close")
    tie = ScreeningConfig.model_validate(raw)
    validate_parent(tie, tmp_path, {"source_manifest_hash": "source"})
    tie.settings.model.num_ctx = 16384
    with pytest.raises(ValueError, match="controls differ"):
        validate_parent(tie, tmp_path, {"source_manifest_hash": "source"})
