from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from run_engineering_repair_probe import schedule, TARGET_IDS, probe_profile, EngineeringProvider
import run_engineering_repair_probe as probe_module
from financial_annotation_harness.config import load_settings
from financial_annotation_harness.ollama_provider import OllamaProvider


def test_probe_is_exactly_five_dev_questions_in_c_and_d_once():
    rows = schedule(ROOT / 'artifacts/dataset_split.json')
    assert len(rows) == 10
    assert {r['question_id'] for r in rows} == TARGET_IDS
    assert {r['condition'] for r in rows} == {'C', 'D'}
    assert {r['run_index'] for r in rows} == {1}
    assert len({(r['run_index'], r['condition'], r['question_id']) for r in rows}) == 10


def test_probe_never_contains_test_questions():
    import json
    split = json.loads((ROOT / 'artifacts/dataset_split.json').read_text(encoding='utf-8'))
    rows = schedule(ROOT / 'artifacts/dataset_split.json')
    assert not {r['question_id'] for r in rows} & set(split['test'])


def test_probe_can_limit_followup_to_cp03_without_changing_conditions():
    rows = schedule(ROOT / 'artifacts/dataset_split.json', {'CP03'})
    assert rows == [
        {'run_index': 1, 'condition': 'C', 'question_id': 'CP03'},
        {'run_index': 1, 'condition': 'D', 'question_id': 'CP03'},
    ]


def test_qwen_probe_uses_separate_config_and_output():
    config, output = probe_profile(qwen=True, only_cp03=True)
    assert config.name == 'experiment.qwen35-9b.probe.json'
    assert output.name == 'qwen35-cp03-probe'


def test_structured_generator_adds_schema_without_changing_model_controls():
    settings = load_settings(ROOT / 'config/experiment.ai-assisted.v1.json')
    base = object.__new__(OllamaProvider)
    candidate = object.__new__(EngineeringProvider)
    base.settings = candidate.settings = settings
    candidate.structured_generator = True
    request = candidate.describe_request('generator', 20260915)
    schema = request.pop('format')
    assert request == base.describe_request('generator', 20260915)
    assert schema['title'] == 'Annotation'
    assert set(schema['required']) >= {'question_id', 'semantic_parse', 'python_solution', 'answer'}


def test_two_phase_probe_has_separate_output():
    _, output = probe_profile(only_cp03=True, two_phase=True)
    assert output.name == 'gemma-two-phase-cp03-probe'


def test_repeat_penalty_probe_uses_separate_config_and_output():
    config, output = probe_profile(only_cp03=True, repeat_penalty=True)
    assert config.name == 'experiment.gemma4.repeat-penalty.probe.json'
    assert output.name == 'gemma-repeat-penalty-cp03-probe'
    settings = load_settings(config)
    assert settings.model.repeat_penalty == 1.1
    assert settings.model.generator_model == 'gemma4:12b'


def test_comparison_feedback_probe_has_revision_specific_output():
    config, output = probe_profile(only_cp03=True, comparison_feedback=True)
    assert config.name == 'experiment.ai-assisted.v1.json'
    assert output.name == 'gemma-comparison-feedback-cp03-probe'


def test_comparison_feedback_can_be_measured_with_repeat_penalty():
    config, output = probe_profile(only_cp03=True, comparison_feedback=True, repeat_penalty=True)
    assert config.name == 'experiment.gemma4.repeat-penalty.probe.json'
    assert output.name == 'gemma-repeat-penalty-comparison-feedback-cp03-probe'


def test_probe_has_no_fallback_output_before_profile_resolution():
    assert probe_module.OUT is None


def test_year_normalization_probe_has_revision_specific_output():
    config, output = probe_profile(
        only_cp03=True, comparison_feedback=True, repeat_penalty=True, year_normalization=True)
    assert config.name == 'experiment.gemma4.repeat-penalty.probe.json'
    assert output.name == 'gemma-year-normalization-cp03-probe'


def test_grounding_feedback_probe_has_revision_specific_output():
    config, output = probe_profile(
        only_cp03=True, comparison_feedback=True, repeat_penalty=True,
        year_normalization=True, grounding_feedback=True)
    assert config.name == 'experiment.gemma4.repeat-penalty.probe.json'
    assert output.name == 'gemma-year-normalization-grounding-feedback-cp03-probe'


def test_unified_comparison_repair_probe_has_revision_specific_output():
    config, output = probe_profile(
        only_cp03=True, comparison_feedback=True, repeat_penalty=True,
        year_normalization=True, grounding_feedback=True, unified_comparison_repair=True)
    assert config.name == 'experiment.gemma4.repeat-penalty.probe.json'
    assert output.name == 'gemma-unified-comparison-repair-cp03-probe'


def test_canonical_final_trace_probe_has_revision_specific_output():
    config, output = probe_profile(
        only_cp03=True, comparison_feedback=True, repeat_penalty=True,
        year_normalization=True, grounding_feedback=True,
        unified_comparison_repair=True, canonical_final_trace=True)
    assert config.name == 'experiment.gemma4.repeat-penalty.probe.json'
    assert output.name == 'gemma-canonical-final-trace-cp03-probe'
