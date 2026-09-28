import json

from financial_annotation_harness.preflight import dev_preflight


def test_dev_preflight_is_offline_and_blocks_only_on_human_review(root):
    report = dev_preflight(root, root / "config/experiment.gemma4.v1.json")
    assert report["no_model_requests"] is True
    assert report["partition"] == "development"
    assert report["expected_question_runs"] == 144
    assert report["conditions"] == ["A", "B", "C", "D"]
    assert report["generator_model"] == report["judge_model"] == "gemma4:12b"
    assert report["status"] == "BLOCKED_HUMAN_REVIEW"
    assert report["blockers"] == ["gold_rules_judge_review"]
