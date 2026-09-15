"""Small real requests on synthetic facts; diagnostic checks never feed B."""
from dataclasses import asdict

from .demo import demo_data
from .facts import FactRepository, create_database, tool_fact
from .io_utils import write_new_json
from .judge import judge_messages, parse_judge
from .model_client import create_provider
from .runner import AnnotationRunner
from .schemas import Annotation
from .trace import TraceStore
from .validators import ValidationContext, validate_all


def run_smoke(config, rules, prompts, output, environment, *, provider_factory=create_provider):
    output.mkdir(parents=True, exist_ok=False)
    source, facts, q, fixture, _ = demo_data()
    create_database(output / "synthetic_facts.sqlite", facts, source)
    repo = FactRepository(output / "synthetic_facts.sqlite")
    questions = [q.model_copy(update={"question_id": "smoke_single", "question": "2025 年營業收入是多少？"}), q]
    write_new_json(output / "manifest.json", {"experiment_kind": "smoke", "screening_config": config.model_dump(),
                                             "environment": environment, "gold_used": False})
    results = []
    calls_total = 0
    aborted = False
    for candidate in config.candidates:
        settings = config.candidate_settings(candidate)
        provider = provider_factory(settings, allow_live=True)
        provider.calls = calls_total
        try:
            with TraceStore(output / candidate.candidate_id) as store:
                runner = AnnotationRunner(settings, repo, rules, prompts, provider, store,
                    trace_context={"experiment_kind": "smoke", "candidate_id": candidate.candidate_id})
                for question in questions:
                    final = runner.run_question(question, source_question_id=question.question_id, condition="B", run_index=1,
                                                experiment_id=f"smoke/{candidate.candidate_id}")
                    attempt = store.read("attempts")[-1]
                    ctx = ValidationContext(question.question_id, question.question, repo, rules, set(attempt.get("candidate_fact_ids", [])))
                    artifact, checks = validate_all(final["artifact"], ctx)
                    results.append({"candidate_id": candidate.candidate_id, "question_id": question.question_id,
                        "kind": "generator", "status": final["final_status"], "schema_pass": artifact is not None,
                        "retrieval_observed": bool(attempt.get("candidate_fact_ids")),
                        "python_execution": ctx.execution, "checks": [c.model_dump(mode="json") for c in checks]})
                    if attempt.get("runtime_error_type") in ("TIMEOUT", "CONNECTION_ERROR", "CALL_BUDGET"):
                        aborted = True
                        break
                if aborted:
                    results.append({"candidate_id": candidate.candidate_id, "kind": "judge", "status": "NOT_RUN",
                                    "reason": "Uncertain inference or exhausted request budget"})
                    break
                # Prefer the genuine generated artifact; use explicitly labeled fixture only for wiring diagnosis.
                selected_artifact = artifact.model_dump() if artifact else fixture
                selected_q = questions[-1].question
                candidates = [tool_fact(f) for f in facts]
                selected = [f for f in candidates if f["fact_id"] in selected_artifact["retrieved_fact_ids"]]
                messages = judge_messages(selected_q, selected_artifact, candidates, selected, prompts["judge"])
                provider.begin_question()
                judge_seed = settings.model.base_seed if settings.model.supports_seed else None
                store.append("events", {"event": "judge_smoke_request", "messages": messages,
                                        "used_fixture": artifact is None, "request_parameters": provider.describe_request("judge", judge_seed)})
                try:
                    turn = provider.complete(messages, [], role="judge", seed=judge_seed)
                    store.append("events", {"event": "judge_smoke_response", "response": asdict(turn)})
                    if turn.tool_calls or turn.finish_reason != "stop":
                        raise ValueError("Incomplete Judge output")
                    verdict = parse_judge(turn.content)
                    results.append({"candidate_id": candidate.candidate_id, "kind": "judge", "schema_pass": True,
                                    "used_fixture": artifact is None, "verdict": verdict.model_dump(mode="json")})
                except Exception as exc:
                    store.append("events", {"event": "judge_smoke_error", "error_type": getattr(exc, "kind", type(exc).__name__)})
                    results.append({"candidate_id": candidate.candidate_id, "kind": "judge", "schema_pass": False,
                                    "error_type": getattr(exc, "kind", type(exc).__name__)})
            provider.verify_identity()
            if hasattr(provider, "unload"):
                provider.unload()
        finally:
            calls_total = provider.calls
            provider.close()
    report = {"experiment_kind": "smoke", "results": results, "requests_attempted": calls_total, "aborted": aborted,
              "note": "Synthetic diagnostic only; no model selection or screening started"}
    write_new_json(output / "smoke_report.json", report)
    return report
