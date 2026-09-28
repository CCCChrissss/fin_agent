import importlib.util
import json
from pathlib import Path
import httpx
import pytest


def test_repair_requires_rationale_in_wire_schema():
    path = Path(__file__).resolve().parents[1] / 'scripts/repair_offline_reviews.py'
    assert path.exists(), 'Dedicated offline repair implementation is required'
    spec = importlib.util.spec_from_file_location('repair', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    schema = module.review_schema()
    assert 'reason' in schema['required']
    assert schema['properties']['reason']['minLength'] == 1
    assert all(k in schema['required'] for k in module.REVIEW_FIELDS)


def load_repair():
    path = Path(__file__).resolve().parents[1] / 'scripts/repair_offline_reviews.py'
    spec = importlib.util.spec_from_file_location('repair', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_actual_http_payload_requires_reason_and_preserves_fresh_messages():
    m = load_repair()
    captured = []
    def receive(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={'ok': True})
    adapter = m.StructuredHTTP('http://127.0.0.1:11434')
    adapter.client.close()
    adapter.client = httpx.Client(base_url='http://127.0.0.1:11434', transport=httpx.MockTransport(receive))
    payload = {'messages': [{'role': 'system', 'content': 'rubric'}, {'role': 'user', 'content': 'visible facts'}], 'model': 'configured-model'}
    try:
        adapter.request('POST', '/api/chat', json=payload)
    finally:
        adapter.close()
    assert captured[0]['format']['required'][-1] == 'reason'
    assert captured[0]['messages'] == payload['messages']
    assert captured[0]['model'] == 'configured-model'
    assert 'format' not in payload


@pytest.mark.parametrize('reason', [None, '', '   ', 123])
def test_repair_never_fills_in_missing_or_invalid_rationale(reason):
    m = load_repair()
    value = {k: True for k in m.REVIEW_FIELDS}
    value['reason'] = reason
    with pytest.raises(ValueError, match='rationale'):
        m.parse_review(json.dumps(value))
