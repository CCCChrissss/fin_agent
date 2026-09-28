import json
from types import SimpleNamespace
import pytest
from financial_annotation_harness.validators import PythonSyntaxValidator, QuestionTypeValidator
from financial_annotation_harness.python_executor import inspect_python
from financial_annotation_harness.model_client import ProviderError
from financial_annotation_harness.ollama_provider import OllamaProvider
from financial_annotation_harness.runner import parse_artifact_json
from financial_annotation_harness.validators import SchemaValidator, ValidationContext
from test_ollama_provider import local_settings, client_for, response

@pytest.mark.parametrize('value,passes', [
    (2025, True), (2025.0, True), (114, True), ('114年', True),
    ('2025', True), ('2025年', True), (True, False), (2022, False),
])
def test_comparison_output_contract(value, passes):
    a = SimpleNamespace(python_solution='def solution():\n    years = {2024: 10, 2025: 20}\n    return max(years, key=years.get)',
        question_type='Comparison', selected_evidence=[SimpleNamespace(fact_id='a'), SimpleNamespace(fact_id='b')],
        semantic_parse=SimpleNamespace(time=[SimpleNamespace(fiscal_year=y) for y in (2024, 2025)]), answer=value)
    c = SimpleNamespace(execution={'success': True, 'result': value}, facts=SimpleNamespace(get=lambda _: None))
    verdict = QuestionTypeValidator().validate(a, c)
    assert (not any(i.rule_id == 'TYPE-03' for i in verdict.issues)) == passes

def test_malformed_response_keeps_diagnostics_without_reasoning_or_retry():
    captured = []
    provider = OllamaProvider(local_settings(), allow_live=True, http_client=client_for(
        lambda _: response({'content': 4, 'thinking': 'private reasoning'}), captured))
    with pytest.raises(ProviderError) as exc:
        provider.complete([], [], role='generator', seed=9)
    d = exc.value.diagnostics
    assert d['response']['message']['content'] == 4
    assert d['parse_error'] == 'Invalid content'
    assert d['request_parameters']['options']['seed'] == 9
    assert 'private reasoning' not in json.dumps(d)
    assert len(captured) == 1

def test_python_feedback_explains_supported_equivalent():
    with pytest.raises(ValueError, match='statement if/else is unsupported'):
        inspect_python('def solution():\n    if 2 > 1:\n        return "Yes"\n    else:\n        return "No"')
    inspect_python('def solution():\n    condition = 2 > 1\n    return "Yes" if condition else "No"')

def test_json_parse_error_is_preserved_as_actionable_schema_feedback():
    parsed, error = parse_artifact_json('{"answer": "unterminated}')
    assert parsed is None
    assert error == 'JSONDecodeError at line 1 column 12: Unterminated string starting at'
    context = ValidationContext('q', 'question', None, {}, input_parse_error=error)
    verdict = SchemaValidator().validate(parsed, context)
    assert verdict.issues[0].observed_value == error
    assert 'valid JSON' in verdict.issues[0].recommended_correction


def test_comparison_statement_if_feedback_gives_supported_year_selection_pattern():
    annotation = SimpleNamespace(
        question_type='Comparison',
        python_solution='def solution():\n    if 20 > 10:\n        return 2025\n    return 2024',
    )
    context = SimpleNamespace(rules={'execution': {}})
    verdict = PythonSyntaxValidator().validate(annotation, context)
    correction = verdict.issues[0].recommended_correction
    assert 'max(values_by_year, key=values_by_year.get)' in correction
    assert 'statement if/elif/else' in correction
    assert 'Keep every selected_evidence variable_name' in correction
    assert 'Do not copy financial literals directly into a differently named dictionary' in correction


def test_comparison_roc_year_label_is_recorded_as_canonical_gregorian():
    annotation = SimpleNamespace(
        python_solution='def solution():\n    values_by_year = {2024: 10, 2025: 20}\n    return max(values_by_year, key=values_by_year.get)',
        question_type='Comparison',
        selected_evidence=[SimpleNamespace(fact_id='a'), SimpleNamespace(fact_id='b')],
        semantic_parse=SimpleNamespace(time=[SimpleNamespace(fiscal_year=y) for y in (2024, 2025)]),
        answer='114年',
    )
    context = SimpleNamespace(execution={'success': True, 'result': '114年'}, facts=SimpleNamespace(get=lambda _: None))
    verdict = QuestionTypeValidator().validate(annotation, context)
    assert not any(issue.rule_id == 'TYPE-03' for issue in verdict.issues)
    assert verdict.measurements['normalized_year_outputs'] == {'answer': 2025, 'python_solution': 2025}


def test_comparison_str_conversion_feedback_says_return_numeric_year_directly():
    annotation = SimpleNamespace(
        question_type='Comparison',
        python_solution=(
            'def solution():\n'
            '    values_by_year = {2024: 10, 2025: 20}\n'
            '    max_year_numeric = max(values_by_year, key=values_by_year.get)\n'
            '    return str(max_year_numeric - 1911) + "年"'),
    )
    context = SimpleNamespace(rules={'execution': {}})
    verdict = PythonSyntaxValidator().validate(annotation, context)
    correction = verdict.issues[0].recommended_correction
    assert 'do not call str()' in correction
    assert 'do not convert it to an ROC year' in correction
    assert 'return the numeric max/min year variable directly' in correction
    assert 'Keep every selected_evidence variable_name' in correction


def test_comparison_join_failure_uses_the_same_safe_replacement_pattern():
    annotation = SimpleNamespace(
        question_type='Comparison',
        python_solution=(
            'def solution():\n'
            '    values_by_year = {2024: 10, 2025: 20}\n'
            '    return "".join([str(max(values_by_year))])'),
    )
    context = SimpleNamespace(rules={'execution': {}})
    verdict = PythonSyntaxValidator().validate(annotation, context)
    correction = verdict.issues[0].recommended_correction
    assert 'max(values_by_year, key=values_by_year.get)' in correction
    assert 'Never add if/elif/else, join(), str(), or lambda' in correction
    assert correction != 'Correct the program within the common restricted Python contract.'
