import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def module():
    path = ROOT / 'scripts/diagnose_dev_judge.py'
    assert path.exists(), 'Judge diagnostic runner has not been implemented'
    spec = importlib.util.spec_from_file_location('diagnose_dev_judge', path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

def test_errors_are_not_semantic_rejections_and_blocked_cases_are_separate():
    m = module()
    rows = [
        {'expected_pass': False, 'deterministic_pass': True, 'verdict': {'overall_pass': False}, 'latency_ms': 1},
        {'expected_pass': False, 'deterministic_pass': True, 'error': 'timeout', 'latency_ms': 2},
        {'expected_pass': False, 'deterministic_pass': False, 'verdict': {'overall_pass': False}, 'latency_ms': 3},
        {'expected_pass': True, 'deterministic_pass': True, 'verdict': {'overall_pass': False}, 'latency_ms': 4},
        {'expected_pass': True, 'deterministic_pass': True, 'verdict': {'overall_pass': True}, 'latency_ms': 5},
    ]
    v = m.metrics(rows)
    assert v['incremental_detection'] == {'numerator': 1, 'denominator': 2, 'rate': .5}
    assert v['false_rejection'] == {'numerator': 1, 'denominator': 2, 'rate': .5}
    assert v['errors'] == 1
    assert v['blocked_errors'] == 1

def test_blind_payload_does_not_contain_case_labels():
    m = module()
    payload = {'original_question': 'question', 'generated_structured_artifact': {},
               'candidate_financial_facts': [], 'selected_financial_facts': []}
    row = {'payload': payload, 'expected_pass': False, 'mutation': 'secret', 'reason': 'hidden'}
    messages = m.blind_messages('rubric', row)
    assert len(messages) == 2
    assert 'secret' not in str(messages) and 'expected_pass' not in str(messages)
    assert m.json.loads(messages[1]['content']) == payload

def test_uncertain_request_is_not_repeated(tmp_path):
    m = module()
    (tmp_path / 'case.request.json').write_text('{}')
    import pytest
    with pytest.raises(RuntimeError, match='Uncertain'):
        m.request_state(tmp_path, 'case')
