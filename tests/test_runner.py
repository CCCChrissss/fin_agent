import json

import pytest

from financial_annotation_harness.config import Settings
from financial_annotation_harness.demo import judge_pass, search_turn
from financial_annotation_harness.model_client import ScriptedClient, Turn
from financial_annotation_harness.runner import AnnotationRunner, completion_gate
from financial_annotation_harness.trace import TraceStore


def execute(tmp_path, specimen, rules, prompts, condition, turns):
    repo, question, *_ = specimen
    client = ScriptedClient(turns)
    with TraceStore(tmp_path / "traces") as store:
        runner = AnnotationRunner(Settings(), repo, rules, prompts, client, store)
        final = runner.run_question(question, source_question_id="SYN01", condition=condition, run_index=1, experiment_id="test")
        return final, store.read("attempts"), client, store.read("events")


@pytest.mark.parametrize("condition", ["A", "B"])
def test_baselines_do_not_validate_repair_or_retry(tmp_path, specimen, rules, prompts, condition, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("A/B must not run validators")
    monkeypatch.setattr("financial_annotation_harness.runner.validate_all", forbidden)
    final, attempts, client, _ = execute(tmp_path, specimen, rules, prompts, condition, [Turn(content="{broken"), judge_pass()])
    assert final["final_status"] == "SUBMITTED"
    assert len(attempts) == len(client.requests) == 1
    assert attempts[0]["raw_response"] == "{broken"
    assert attempts[0]["validator_results"] == {} and attempts[0]["judge_result"] is None


def test_c_repairs_on_second_attempt_without_judge(tmp_path, specimen, rules, prompts):
    good = specimen[2]
    wrong = {**good, "answer": 99}
    final, attempts, client, events = execute(tmp_path, specimen, rules, prompts, "C",
                                             [search_turn(), Turn(content=json.dumps(wrong)), Turn(content=json.dumps(good))])
    assert final["final_status"] == "VALIDATED" and final["attempt"] == 2
    assert attempts[0]["artifact"]["answer"] == 99
    assert attempts[0]["failure_codes"] == ["PYTHON_ANSWER_MISMATCH"]
    assert all(r["role"] == "generator" for r in client.requests)
    assert any(e["event"] == "tool_result" for e in events)
    assert "expected_constraint" in client.requests[-1]["messages"][-1]["content"]


def test_c_records_comparison_years_as_canonical_gregorian_without_changing_raw_artifact(
        tmp_path, specimen, rules, prompts):
    artifact = {**specimen[2], 'question_type': 'Comparison', 'unit': 'year', 'answer': '114年'}
    artifact['python_solution'] = (
        'def solution():\n'
        '    revenue_2024 = 100\n'
        '    revenue_2025 = 120\n'
        '    values_by_year = {2024: revenue_2024, 2025: revenue_2025}\n'
        '    labels_by_year = {2024: "113年", 2025: "114年"}\n'
        '    return labels_by_year[max(values_by_year, key=values_by_year.get)]')
    final, attempts, _, _ = execute(
        tmp_path, specimen, rules, prompts, 'C', [search_turn(), Turn(content=json.dumps(artifact))])
    assert final['final_status'] == 'VALIDATED'
    assert attempts[0]['artifact']['answer'] == '114年'
    assert attempts[0]['python_result'] == '114年'
    assert attempts[0]['normalized_answer'] == 2025
    assert attempts[0]['normalized_python_result'] == 2025
    assert final['normalized_answer'] == 2025
    assert final['normalized_python_result'] == 2025


def test_c_stops_after_three_attempts(tmp_path, specimen, rules, prompts):
    final, attempts, client, _ = execute(tmp_path, specimen, rules, prompts, "C", [Turn(content="{}") for _ in range(4)])
    assert final["final_status"] == "FAILED" and final["attempt"] == 3
    assert len(attempts) == len(client.requests) == 3


def semantic_failure():
    return Turn(content=json.dumps({"semantic_parse_pass": True, "concept_pass": False, "evidence_pass": True,
        "golden_context_pass": True, "overall_pass": False, "failure_codes": ["CONCEPT_ERROR"],
        "issues": [{"failure_code": "CONCEPT_ERROR", "rule_id": "SEM-CONCEPT", "field_path": "semantic_parse.concept",
                    "observed_value": "wrong", "expected_constraint": "requested concept", "recommended_correction": "Fix concept mapping."}],
        "feedback": "Fix concept mapping."}))


def test_d_shared_retry_budget_and_fresh_judge(tmp_path, specimen, rules, prompts):
    good = specimen[2]
    wrong = {**good, "answer": 99}
    final, attempts, client, _ = execute(tmp_path, specimen, rules, prompts, "D", [search_turn(),
        Turn(content=json.dumps(wrong)), Turn(content=json.dumps(good)), semantic_failure(),
        Turn(content=json.dumps(good)), judge_pass()])
    assert final["final_status"] == "ACCEPTED" and final["attempt"] == 3
    judges = [r for r in client.requests if r["role"] == "judge"]
    assert len(judges) == 2
    assert all(len(r["messages"]) == 2 for r in judges)
    assert "validation_feedback" not in judges[-1]["messages"][1]["content"]
    assert attempts[0]["judge_result"] is None


def test_invalid_judge_fails_closed_without_resampling(tmp_path, specimen, rules, prompts):
    final, attempts, client, _ = execute(tmp_path, specimen, rules, prompts, "D", [search_turn(),
        Turn(content=json.dumps(specimen[2])), Turn(content="not JSON"), judge_pass()])
    assert final["final_status"] == "FAILED"
    assert "OTHER" in final["failure_codes"]
    assert len(attempts) == 1 and len(client.requests) == 3


def test_online_requests_do_not_contain_gold_or_source_id(tmp_path, specimen, rules, prompts):
    final, _, client, _ = execute(tmp_path, specimen, rules, prompts, "D", [search_turn(), Turn(content=json.dumps(specimen[2])), judge_pass()])
    assert final["final_status"] == "ACCEPTED"
    sent = json.dumps(client.requests)
    assert "SYN01" not in sent
    assert "Gold_Answer" not in sent and "Source_Fact_IDs" not in sent


def test_completed_resume_makes_zero_requests(tmp_path, specimen, rules, prompts):
    repo, q, artifact, _ = specimen
    with TraceStore(tmp_path / "resume") as store:
        first = AnnotationRunner(Settings(), repo, rules, prompts, ScriptedClient([Turn(content=json.dumps(artifact))]), store)
        final = first.run_question(q, source_question_id="SYN01", condition="A", run_index=1, experiment_id="test")
        empty = ScriptedClient([])
        second = AnnotationRunner(Settings(), repo, rules, prompts, empty, store)
        assert second.run_question(q, source_question_id="SYN01", condition="A", run_index=1, experiment_id="test") == final
        assert empty.requests == []


def test_uncertain_request_sealed_without_resampling(tmp_path, specimen, rules, prompts):
    repo, q, *_ = specimen
    with TraceStore(tmp_path / "interrupted") as store:
        store.append("events", {"question_id": "SYN01", "event": "generator_request"})
        client = ScriptedClient([])
        runner = AnnotationRunner(Settings(), repo, rules, prompts, client, store)
        final = runner.run_question(q, source_question_id="SYN01", condition="C", run_index=1, experiment_id="test")
        assert final["final_status"] == "FAILED" and client.requests == []


def test_gate_requires_every_validator(specimen, rules):
    from financial_annotation_harness.validators import validate_all, ValidationContext
    from financial_annotation_harness.judge import parse_judge
    repo, q, artifact, _ = specimen
    _, checks = validate_all(artifact, ValidationContext(q.question_id, q.question, repo, rules, set(artifact["retrieved_fact_ids"])))
    verdict = parse_judge(judge_pass().content)
    assert completion_gate(checks, verdict)
    assert not completion_gate(checks[:-1], verdict)
    checks[4].status = "SKIPPED"
    assert not completion_gate(checks, verdict)


class TwoPhaseScriptedClient(ScriptedClient):
    two_phase_generator = True

    def describe_completion_request(self, role, seed, tools):
        return {'role': role, 'seed': seed, 'format': 'annotation-schema' if role == 'generator' and not tools else None}


def test_two_phase_generator_retrieves_before_schema_finalization(tmp_path, specimen, rules, prompts):
    repo, question, artifact, _ = specimen
    client = TwoPhaseScriptedClient([search_turn(), Turn(content=json.dumps(artifact))])
    with TraceStore(tmp_path / 'two-phase') as store:
        runner = AnnotationRunner(Settings(), repo, rules, prompts, client, store)
        final = runner.run_question(question, source_question_id='SYN01', condition='C', run_index=1, experiment_id='test')
        events = store.read('events')
    assert final['final_status'] == 'VALIDATED'
    generator_requests = [r for r in client.requests if r['role'] == 'generator']
    assert generator_requests[0]['tools']
    assert generator_requests[1]['tools'] == []
    transitions = [e for e in events if e['event'] == 'generator_phase_transition']
    assert len(transitions) == 1 and transitions[0]['phase'] == 'structured_finalization'
    final_request = [e for e in events if e['event'] == 'generator_request'][-1]
    assert final_request['request_parameters']['format'] == 'annotation-schema'
