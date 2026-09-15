import copy

import pytest

from financial_annotation_harness.demo import demo_data, run_demo
from financial_annotation_harness.evaluation import REVIEW_FIELDS, aggregate_run, evaluate_experiment, evaluate_scope, evidence_metrics, score_attempt
from financial_annotation_harness.facts import FactRepository
from financial_annotation_harness.io_utils import digest, read_jsonl


def attempt_for(artifact):
    return {"run_id": "example/1/A", "question_id": "SYN01", "run_index": 1, "condition": "A", "attempt": 1,
            "artifact": artifact, "artifact_hash": digest(artifact), "candidate_fact_ids": artifact["retrieved_fact_ids"],
            "final_status": "SUBMITTED"}


def test_evidence_counts():
    m = evidence_metrics({"a", "x"}, {"a", "b", "c"})
    assert m["evidence_precision"] == 0.5
    assert m["evidence_recall"] == pytest.approx(1/3)
    assert m["evidence_f1"] == pytest.approx(0.4)
    assert m["evidence_tp"] == 1 and m["evidence_fp"] == 1 and m["evidence_fn"] == 2
    assert evidence_metrics(set(), {"a"})["evidence_f1"] == 0


def test_missing_human_review_never_becomes_e2e_pass(specimen, rules):
    repo, question, artifact, gold = specimen
    scored = score_attempt(attempt_for(artifact), gold, question.model_dump(), repo, rules)
    assert scored["answer_accuracy"] == 1
    assert scored["e2e"] is None and scored["review_pending"]
    summary = aggregate_run([scored], [scored])
    assert summary["e2e_accuracy"] is None
    assert summary["recovery_rate"] is None


def test_consistent_wrong_answer_not_python_correct(specimen, rules):
    repo, question, artifact, gold = specimen
    wrong = copy.deepcopy(artifact)
    wrong["answer"] = 99
    wrong["python_solution"] = wrong["python_solution"].replace("return round(growth * 100, 2)", "return 99")
    row = attempt_for(wrong)
    review = {"artifact_hash": row["artifact_hash"], "reviewer": "fixture", **{k: True for k in REVIEW_FIELDS}}
    score = score_attempt(row, gold, question.model_dump(), repo, rules, review)
    assert score["python_answer_consistency"] == 1
    assert score["answer_accuracy"] == score["python_accuracy"] == score["e2e"] == 0


def test_synthetic_end_to_end_and_metrics(tmp_path, rules, prompts):
    output = tmp_path / "demo"
    report = run_demo(output, rules, prompts)
    assert report["expected_question_runs"] == report["observed_question_runs"] == 12
    assert report["mode"] == "synthetic_demo"
    for condition in "AB":
        assert report["metrics"][condition]["e2e_accuracy"]["mean"] == 0
        assert report["metrics"][condition]["recovery_rate"]["mean"] == 0
    for condition in "CD":
        assert report["metrics"][condition]["e2e_accuracy"]["mean"] == 1
        assert report["metrics"][condition]["first_pass_accuracy"]["mean"] == 0
        assert report["metrics"][condition]["recovery_rate"]["mean"] == 1
    assert report["metrics"]["D"]["e2e_accuracy"]["sample_sd"] == 0


def test_missing_question_runs_rejected(tmp_path, rules, prompts):
    output = tmp_path / "demo"
    run_demo(output, rules, prompts)
    # Intentional fixture corruption, never an actual experiment deletion.
    (output / "run_03/D/finals.jsonl").write_text("")
    _, _, q, _, gold = demo_data()
    with pytest.raises(ValueError, match="Incomplete experiment"):
        evaluate_experiment(output, [gold], [q.model_dump()], FactRepository(output / "financial_facts.sqlite"), rules, output / "evaluation2")


def test_scope_metrics_separate_and_degenerate_warning():
    rows = [{"question_id": "a", "gold_out_of_scope": True, "status": "OUT_OF_SCOPE", "answer": None},
            {"question_id": "b", "gold_out_of_scope": True, "status": "ANSWERED", "answer": 1},
            {"question_id": "c", "gold_out_of_scope": False, "status": "OUT_OF_SCOPE", "answer": None}]
    report = evaluate_scope(rows)
    assert report["precision"] == report["recall"] == report["f1"] == 0.5
    assert report["unsupported_answer_rate"] == pytest.approx(1/3)
    assert evaluate_scope(rows[:2])["warning"] is not None


def test_scope_failure_is_not_correct_negative():
    report = evaluate_scope([{"question_id": "a", "gold_out_of_scope": False, "status": "FAILED", "answer": None}])
    assert report["scope_detection_accuracy"] == 0
    assert report["tn"] == 0 and report["failed_count"] == 1


def test_recovery_undefined_when_initially_all_correct(specimen, rules):
    repo, question, artifact, gold = specimen
    attempt = attempt_for(artifact)
    review = {"artifact_hash": attempt["artifact_hash"], "reviewer": "fixture", **{k: True for k in REVIEW_FIELDS}}
    row = score_attempt(attempt, gold, question.model_dump(), repo, rules, review)
    summary = aggregate_run([row], [row])
    assert summary["final_accuracy"] == 1
    assert summary["recovery_denominator"] == 0
    assert summary["recovery_rate"] is None
