"""Independent offline screening scoring; never called from generation."""
import csv
import json
import statistics
from collections import defaultdict

from .evaluation import REVIEW_FIELDS, mean_complete, review_key, score_attempt
from .io_utils import digest, read_json, write_new_json, write_new_jsonl
from .screening import ScreeningConfig, screening_schedule
from .trace import TraceStore


def diagnostics(attempt, gold):
    raw = attempt.get("raw_response")
    parse_ok = False
    if raw is not None:
        try:
            json.loads(raw, parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))
            parse_ok = True
        except (ValueError, TypeError):
            pass
    calls = attempt.get("tool_calls", [])
    needed = {f.strip() for f in gold["gold_annotation"]["Source_Fact_IDs"].split(";")}
    found = {f["fact_id"] for c in calls for f in c["result"].get("candidates", [])}
    durations = [r.get("runtime", {}).get("durations_ns", {}).get("load_duration") for r in attempt.get("generator_responses", [])]
    return {"json_parse_success": int(parse_ok), "no_output": int(raw is None),
            "unparseable_output": int(raw is not None and not parse_ok),
            "retrieval_success": int(bool(calls) and needed <= found),
            "candidate_recall": len(needed & found) / len(needed) if needed else None,
            "nonempty_retrieval": int(bool(found)), "tool_call_count": len(calls),
            "successful_tool_calls": sum(c["result"].get("success") is True for c in calls),
            "runtime_error_type": attempt.get("runtime_error_type"),
            "timeout": int(attempt.get("runtime_error_type") == "TIMEOUT"),
            "inference_failure": int(bool(attempt.get("infrastructure_error"))),
            "latency_ms": attempt.get("latency_ms"),
            "load_duration_ms": sum(durations) / 1_000_000 if durations and all(v is not None for v in durations) else None}


def summarize(rows):
    result = {"question_count": len(rows)}
    for source, target in (("e2e", "e2e_accuracy"), ("schema_accuracy", "schema_success_rate"),
            ("json_parse_success", "json_parse_success_rate"), ("evidence_precision", "evidence_precision"),
            ("evidence_recall", "evidence_recall"), ("evidence_f1", "evidence_f1"),
            ("python_execution_rate", "python_execution_rate"), ("answer_accuracy", "answer_accuracy"),
            ("retrieval_success", "financial_fact_retrieval_success"), ("candidate_recall", "candidate_recall"),
            ("nonempty_retrieval", "nonempty_retrieval_rate"), ("latency_ms", "mean_latency_ms")):
        result[target] = mean_complete(r[source] for r in rows)
    for field in ("timeout", "inference_failure", "unparseable_output", "no_output", "review_pending"):
        result[f"{field}_count"] = sum(r[field] for r in rows)
    result["request_count"] = sum(r["request_count"] for r in rows)
    result["request_failure_event_count"] = sum(r["request_failure_event_count"] for r in rows)
    result["schema_invalid_json_count"] = sum(r["json_parse_success"] and not r["schema_accuracy"] for r in rows)
    tool_count = sum(r["tool_call_count"] for r in rows)
    result["tool_execution_success_rate"] = sum(r["successful_tool_calls"] for r in rows) / tool_count if tool_count else None
    successful_latency = [r["latency_ms"] for r in rows if not r["inference_failure"] and r["latency_ms"] is not None]
    result["mean_submitted_latency_ms"] = statistics.mean(successful_latency) if successful_latency else None
    latencies = [r["latency_ms"] for r in rows if r["latency_ms"] is not None]
    result["median_latency_ms"] = statistics.median(latencies) if latencies else None
    tp, fp, fn = (sum(r[k] for r in rows) for k in ("evidence_tp", "evidence_fp", "evidence_fn"))
    result.update(evidence_micro_precision=tp / (tp + fp) if tp + fp else 0,
                  evidence_micro_recall=tp / (tp + fn) if tp + fn else None,
                  evidence_micro_f1=2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0)
    return result


def evaluate_screenings(directories, gold_rows, questions, repo, rules, split, output, reviews=None, *, evaluation_provenance=None):
    labels = {r["review_id"]: r for r in reviews or []}
    if len(labels) != len(reviews or []):
        raise ValueError("Duplicate review IDs")
    gold_map = {r["question_id"]: r for r in gold_rows if r["question_id"] in split["development"]}
    scores, queue, manifests, observed = [], [], [], set()
    for directory in directories:
        manifest = read_json(directory / "manifest.json")
        config = ScreeningConfig.model_validate(manifest["screening_config"])
        if manifest["experiment_kind"] != "screening" or manifest["expected_runs"] != screening_schedule(config, split):
            raise ValueError("Not a valid Development screening manifest")
        if manifests:
            first = manifests[0]
            first_config = ScreeningConfig.model_validate(first["screening_config"])
            if config.stage != "tie_break" or first_config.stage != "initial" or config.settings != first_config.settings:
                raise ValueError("Combined evaluation requires initial followed by its tie-break")
            if config.order_seed != first_config.order_seed or config.warmup_requests != first_config.warmup_requests:
                raise ValueError("Combined evaluation changed ordering/warmup controls")
            for key in ("source_manifest_hash", "split_hash", "project_hashes"):
                if manifest[key] != first[key]:
                    raise ValueError("Mixed screening provenance")
            if any(c not in first_config.candidates for c in config.candidates):
                raise ValueError("Mixed candidate profiles")
        manifests.append(manifest)
        lifecycle = TraceStore(directory).read("events")
        completed = {e["candidate_id"] for e in lifecycle if e["event"] == "candidate_complete"}
        if completed != {c.candidate_id for c in config.candidates}:
            raise ValueError("Screening lifecycle incomplete or terminal model verification failed")
        for candidate in config.candidates:
            for run in config.run_indices:
                store = TraceStore(directory / candidate.candidate_id / f"run_{run:02d}" / "B")
                events, attempts, finals = (store.read(k) for k in ("events", "attempts", "finals"))
                if len(attempts) != 12 or len(finals) != 12:
                    raise ValueError("Incomplete screening; failed runs must be sealed, not dropped")
                by_id = {a["question_id"]: a for a in attempts}
                if set(by_id) != set(split["development"]):
                    raise ValueError("Screening attempts do not match Development")
                for final in finals:
                    a = by_id[final["question_id"]]
                    key = candidate.candidate_id, run, a["question_id"]
                    if key in observed:
                        raise ValueError("Duplicate model/run/question")
                    observed.add(key)
                    if a["attempt"] != 1 or a["condition"] != "B" or a["run_index"] != run or a["validator_results"] or a["judge_result"]:
                        raise ValueError("Screening condition B was changed")
                    if final["attempt_record_hash"] != a["record_hash"] or final["artifact"] != a["artifact"] or final["artifact_hash"] != a["artifact_hash"]:
                        raise ValueError("Invalid terminal linkage")
                    if a["artifact_hash"] != (digest(a["artifact"]) if a["artifact"] is not None else None):
                        raise ValueError("Invalid artifact hash")
                    qevents = [e for e in events if e.get("question_id") == a["question_id"]]
                    if not qevents or any(e["event"].startswith("judge_") for e in qevents):
                        raise ValueError("Missing events or Judge leakage")
                    if a.get("model") != candidate.model_tag or a.get("model_version") != candidate.digest:
                        raise ValueError("Attempt model identity does not match screening candidate")
                    traced_calls = [e for e in qevents if e["event"] == "tool_result"]
                    if [e["result"] for e in traced_calls] != [c["result"] for c in a.get("tool_calls", [])]:
                        raise ValueError("Attempt tool results differ from event journal")
                    gold, q = gold_map[a["question_id"]], questions[a["question_id"]]
                    scored = score_attempt(a, gold, q.model_dump(), repo, rules, labels.get(review_key(a)))
                    # Measure execution stability even if a different schema field is invalid.
                    if not scored["schema_accuracy"] and isinstance(a.get("artifact"), dict) and isinstance(a["artifact"].get("python_solution"), str):
                        from .python_executor import execute_python
                        executed = execute_python(a["artifact"]["python_solution"], **rules["execution"])
                        scored["python_execution_rate"] = int(executed["success"])
                    scored.update(candidate_id=candidate.candidate_id, **diagnostics(a, gold))
                    scored["request_count"] = sum(e["event"] == "generator_request" for e in qevents)
                    scored["request_failure_event_count"] = sum(e["event"] == "runtime_error" for e in qevents)
                    scores.append(scored)
                    if scored["review_pending"]:
                        g, bank = gold["gold_annotation"], gold["question_bank"]
                        queue.append({"review_id": scored["review_id"], "artifact_hash": a["artifact_hash"],
                            "question": q.question, "generated_artifact": a["artifact"],
                            "reference": {"time": bank["Time"], "concept": bank["Concept"], "filter": bank["Filter"],
                                          "logic": bank["Logic"], "golden_context": g["Golden_Context"], "python_solution": g["Python_Solution"]},
                            "reviewer": "", **{f: None for f in REVIEW_FIELDS}})
    if set(labels) - {s["review_id"] for s in scores}:
        raise ValueError("Unknown review IDs")
    per_model, per_run = [], []
    for candidate in sorted({s["candidate_id"] for s in scores}):
        rows = [s for s in scores if s["candidate_id"] == candidate]
        runs = sorted({s["run_index"] for s in rows})
        summaries = [summarize([s for s in rows if s["run_index"] == r]) for r in runs]
        per_run.extend({"candidate_id": candidate, "run_index": r, **m} for r, m in zip(runs, summaries))
        metrics = summarize(rows)
        values = [m["e2e_accuracy"] for m in summaries]
        metrics["e2e_sample_sd"] = statistics.stdev(values) if len(values) > 1 and all(v is not None for v in values) else None
        per_model.append({"candidate_id": candidate, "run_count": len(runs), **metrics})
    output.mkdir(parents=True, exist_ok=False)
    write_new_jsonl(output / "per_question.jsonl", scores)
    write_new_jsonl(output / "review_queue.jsonl", sorted(queue, key=lambda r: r["review_id"]))
    write_new_jsonl(output / "per_run.jsonl", per_run)
    with (output / "model_comparison.csv").open("x", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(per_model[0]))
        writer.writeheader()
        writer.writerows(per_model)
    summary = {"experiment_kind": "screening", "question_runs": len(scores), "pending_reviews": len(queue),
               "models": per_model, "manifest_hashes": [digest(m) for m in manifests], "review_labels_hash": digest(reviews or []),
               "candidate_profiles": manifests[0]["screening_config"]["candidates"],
               "ollama_version": manifests[0]["screening_config"]["settings"]["model"]["expected_ollama_version"],
               "winner": None, "note": "Human selection required. Screening Gold is provisional until Gold Review."}
    if evaluation_provenance is not None:
        summary["evaluation_provenance"] = evaluation_provenance
        write_new_json(output / "evaluation_provenance.json", evaluation_provenance)
    write_new_json(output / "summary.json", summary)
    write_new_json(output / "selection_template.json", {"reviewer": "", "reason": "", "candidate_id": "",
                   "evaluation_summary_hash": digest(summary), "evaluation_summary_path": "", "model_tag": "", "digest": "", "quantization": "",
                   "ollama_version": "", "screening_config_hash": "", "status": "DRAFT"})
    return summary
