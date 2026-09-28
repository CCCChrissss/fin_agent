import pytest
from financial_annotation_harness.config import Settings
from financial_annotation_harness.governance import review_provenance
from financial_annotation_harness.io_utils import write_new_json, file_hash


def test_ai_review_requires_record_and_exact_source(tmp_path):
    settings = Settings(review_mode="ai_assisted", review_record="review.json")
    with pytest.raises((ValueError, FileNotFoundError)):
        review_provenance(tmp_path, settings, {"sha256": "gold"})
    write_new_json(tmp_path / "review.json", {
        "review_kind": "ai_assisted", "reviewer": "Codex AI", "status": "COMPLETE",
        "source_sha256": "gold", "question_count": 60, "reviewed_question_count": 60,
        "rules_reviewed": True, "judge_rubric_reviewed": True,
    })
    result = review_provenance(tmp_path, settings, {"sha256": "gold"})
    assert result["review_mode"] == "ai_assisted"
    assert result["review_record_hash"] == file_hash(tmp_path / "review.json")
    with pytest.raises(ValueError, match="source"):
        review_provenance(tmp_path, settings, {"sha256": "different"})


def test_default_retains_human_review():
    assert Settings().review_mode == "human"
