import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from run_dev_prompt_v2 import schedule, CandidateProvider, dev_profile
import run_dev_prompt_v2 as dev_module
from financial_annotation_harness.config import load_settings
from financial_annotation_harness.ollama_provider import OllamaProvider
from financial_annotation_harness.io_utils import read_json


def test_exact_dev_schedule_and_reject_overlap():
    split = read_json(ROOT / 'artifacts/dataset_split.json')
    rows = schedule(split)
    assert len(rows) == 144
    assert len({tuple(r.values()) for r in rows}) == 144
    assert {r['question_id'] for r in rows} == set(split['development'])
    assert not {r['question_id'] for r in rows} & set(split['test'])
    with pytest.raises(ValueError):
        schedule({**split, 'test': split['test'] + split['development'][:1]})


def test_schema_override_never_changes_generator_controls():
    settings = load_settings(ROOT / 'config/experiment.ai-assisted.v1.json')
    base = object.__new__(OllamaProvider)
    candidate = object.__new__(CandidateProvider)
    base.settings = candidate.settings = settings
    for seed in (20260915, 20260916, 20260917):
        assert candidate.describe_request('generator', seed) == base.describe_request('generator', seed)
        judge = candidate.describe_request('judge', seed)
        schema = judge.pop('format')
        assert judge == base.describe_request('judge', seed)
        assert schema['$defs']['FailureCode']['enum'] == ['SEMANTIC_PARSE_ERROR', 'CONCEPT_ERROR', 'EVIDENCE_ERROR', 'UNSUPPORTED_ANSWER']
    candidate.offline = True
    assert 'reason' in candidate.describe_request('judge', 1)['format']['required']
    assert candidate.describe_request('generator', 1) == base.describe_request('generator', 1)


def test_v3_profile_uses_repaired_config_and_separate_output():
    config, output, stage = dev_profile(candidate_v3=True)
    settings = load_settings(config)
    assert config.name == 'experiment.dev-candidate-v3.json'
    assert output.name == 'full-dev-v3'
    assert stage == 'development_candidate_v3'
    assert settings.model.generator_model == 'gemma4:12b'
    assert settings.model.repeat_penalty == 1.1
    assert settings.conditions == ['A', 'B', 'C', 'D']
    assert settings.runs_per_condition == 3


def test_dev_runner_has_no_fallback_output_before_profile_resolution():
    assert dev_module.OUT is None


def test_v4_profile_is_isolated_but_keeps_v3_model_controls():
    config, output, stage = dev_profile(candidate_v4=True)
    old_config, old_output, _ = dev_profile(candidate_v3=True)
    assert config == old_config
    assert output != old_output and output.name == 'full-dev-v4'
    assert stage == 'development_year_fix_v4'


def test_noncritical_ui_lock_does_not_stop_experiment(tmp_path, monkeypatch):
    monkeypatch.setattr(dev_module, 'OUT', tmp_path)
    def locked(*a, **kw):
        raise PermissionError('file busy')
    monkeypatch.setattr(Path, 'replace', locked)
    monkeypatch.setattr(dev_module, 'render_report', locked)
    dev_module.status('OFFLINE_REVIEW', processed=1, total=2)
    assert list(tmp_path.glob('status-event-*.json'))
