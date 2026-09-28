import importlib.util
import json
from pathlib import Path
import pytest


def load_script():
    path = Path(__file__).resolve().parents[1] / "scripts/complete_ai_study.py"
    spec = importlib.util.spec_from_file_location("study", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_offline_labels_fail_closed_on_malformed_or_missing_criteria():
    m = load_script()
    with pytest.raises(ValueError):
        m.parse_review('{"time_pass": true}')
    good = {key: True for key in m.REVIEW_FIELDS}
    good["reason"] = "Reviewed visible semantic and program operations."
    assert m.parse_review(json.dumps(good))["time_pass"] is True
    good["time_pass"] = "true"
    with pytest.raises(ValueError):
        m.parse_review(json.dumps(good))


def test_offline_review_request_contains_no_gold_or_online_verdict():
    m = load_script()
    row = {"question": "test question", "generated_artifact": {"answer": 12},
           "reference": {"gold_answer": "SECRET"}, "judge_result": "SECRET"}
    messages = m.review_messages(row, [])
    encoded = json.dumps(messages)
    assert "SECRET" not in encoded
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
