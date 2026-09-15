from financial_annotation_harness.screening_evaluation import diagnostics


def test_complete_screening_evaluation_and_blind_reviews(tmp_path, specimen, rules, prompts):
    import json
    from financial_annotation_harness.demo import search_turn
    from financial_annotation_harness.evaluation import REVIEW_FIELDS
    from financial_annotation_harness.io_utils import read_jsonl
    from financial_annotation_harness.model_client import Turn
    from financial_annotation_harness.screening import run_screening
    from financial_annotation_harness.screening_evaluation import evaluate_screenings
    from test_screening import screening_config, split_fixture, FakeProvider
    repo, q, artifact, gold = specimen
    config, split = screening_config(), split_fixture()
    # Preserve one neutral question identity in this synthetic metric fixture.
    questions = {qid: q for qid in split["development"]}
    golds = [{**gold, "question_id": qid} for qid in split["development"]]
    def factory(*args, **kwargs):
        turns = []
        for i in range(12):
            turns.extend([search_turn(), Turn(content=json.dumps(artifact))])
        return FakeProvider(turns)
    out = tmp_path / "screen"
    run_screening(config, split, questions, repo, rules, prompts, out, {}, {}, provider_factory=factory)
    report = evaluate_screenings([out], golds, questions, repo, rules, split, out / "eval")
    assert report["question_runs"] == report["pending_reviews"] == 24
    assert len(report["models"]) == 2
    assert all(m["e2e_accuracy"] is None and m["financial_fact_retrieval_success"] == 1 for m in report["models"])
    queue = read_jsonl(out / "eval/review_queue.jsonl")
    assert queue == sorted(queue, key=lambda r: r["review_id"])
    assert all("candidate_id" not in r and "run_index" not in r for r in queue)
    reviews = [{**r, "reviewer": "fixture-human", **{f: True for f in REVIEW_FIELDS}} for r in queue]
    reviewed = evaluate_screenings([out], golds, questions, repo, rules, split, out / "reviewed", reviews)
    assert reviewed["pending_reviews"] == 0 and all(m["e2e_accuracy"] == 1 for m in reviewed["models"])
    assert reviewed["winner"] is None


def test_retrieval_distinct_from_selection(specimen):
    _, _, artifact, gold = specimen
    ids = artifact["retrieved_fact_ids"]
    result = diagnostics({"raw_response": "{}", "tool_calls": [{"result": {"success": True, "candidates": [{"fact_id": i} for i in ids]}}]}, gold)
    assert result["retrieval_success"] == 1 and result["candidate_recall"] == 1
    assert result["json_parse_success"] == 1


def test_timeout_and_malformed_separate(specimen):
    gold = specimen[3]
    timeout = diagnostics({"runtime_error_type": "TIMEOUT", "infrastructure_error": "timeout"}, gold)
    malformed = diagnostics({"raw_response": "```json\n{}\n```"}, gold)
    assert timeout["no_output"] == timeout["timeout"] == timeout["inference_failure"] == 1
    assert timeout["unparseable_output"] == 0
    assert malformed["unparseable_output"] == 1 and malformed["timeout"] == 0
