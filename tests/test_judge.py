import json

import pytest

from financial_annotation_harness.demo import judge_pass
from financial_annotation_harness.judge import judge_messages, parse_judge


def test_judge_payload_is_only_authorized_context():
    messages = judge_messages("question", {"answer": 1}, [], [], "rubric")
    assert len(messages) == 2
    assert set(json.loads(messages[1]["content"])) == {"original_question", "generated_structured_artifact", "candidate_financial_facts", "selected_financial_facts"}


@pytest.mark.parametrize("mutation", [
    {"overall_pass": False}, {"failure_codes": ["WRONG_EVIDENCE"]},
    {"failure_codes": ["PYTHON_EXECUTION_ERROR"]}, {"semantic_parse_pass": "true"}, {"extra": "field"},
])
def test_judge_invalid_result(mutation):
    raw = json.loads(judge_pass().content)
    raw.update(mutation)
    with pytest.raises(ValueError):
        parse_judge(json.dumps(raw))

