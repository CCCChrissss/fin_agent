"""Gold-based offline evaluation. No model requests, no feedback to runner."""

from __future__ import annotations

import csv
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from .facts import UNIT_MAP
from .io_utils import digest, read_json, read_jsonl, timestamp, write_new_json, write_new_jsonl
from .schemas import Annotation
from .trace import TraceStore
from .validators import ValidationContext, answer_equal, normalize_unit, validate_all

REVIEW_FIELDS = ("time_pass", "concept_pass", "filter_pass", "logic_pass",
                 "evidence_relevance_pass", "golden_context_sufficiency_pass", "python_reasoning_pass")


def evidence_metrics(predicted: set[str], gold: set[str]) -> dict:
    tp, fp, fn = len(predicted & gold), len(predicted - gold), len(gold - predicted)
    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(gold) if gold else None
    f1 = 2 * precision * recall / (precision + recall) if recall is not None and precision + recall else 0.0
    return {"evidence_precision": precision, "evidence_recall": recall, "evidence_f1": f1,
            "evidence_tp": tp, "evidence_fp": fp, "evidence_fn": fn}


def conjunction(values) -> int | None:
    values = list(values)
    if any(v is False or v == 0 for v in values):
        return 0
    return None if any(v is None for v in values) else 1


def review_key(attempt: dict) -> str:
    return digest([attempt["run_id"], attempt["question_id"], attempt["attempt"], attempt.get("artifact_hash")])


def score_attempt(attempt, gold, question, facts, rules, review=None) -> dict:
    raw = attempt.get("artifact")
    candidate_ids = set(attempt.get("candidate_fact_ids", []))
    context = ValidationContext(question["question_id"], question["question"], facts, rules, candidate_ids)
    artifact, validations = validate_all(raw, context)
    checks = {v.validator_name: v.status == "PASS" for v in validations}
    g = gold["gold_annotation"]
    expected_ids = {fid.strip() for fid in g["Source_Fact_IDs"].split(";")}
    predicted = set(artifact.retrieved_fact_ids) if artifact else set()
    metrics = evidence_metrics(predicted, expected_ids)
    semantic = None
    python_reasoning = None
    evidence_semantics = None
    if review:
        if review.get("artifact_hash") != attempt.get("artifact_hash") or not review.get("reviewer"):
            raise ValueError("Review must identify the exact artifact and its human reviewer")
        if any(type(review.get(f)) is not bool for f in REVIEW_FIELDS):
            raise ValueError("Every independent review criterion must be a boolean")
        semantic = all(review[f] for f in REVIEW_FIELDS[:4])
        python_reasoning = review["python_reasoning_pass"]
        evidence_semantics = review["evidence_relevance_pass"] and review["golden_context_sufficiency_pass"]
    valid = artifact is not None
    executed = bool(context.execution and context.execution["success"])
    unit_pass = valid and normalize_unit(artifact.unit) == normalize_unit(g["Unit"]) and checks["UnitValidator"]
    answer_pass = valid and normalize_unit(artifact.unit) == normalize_unit(g["Unit"]) and answer_equal(artifact.answer, g["Gold_Answer"], g["Unit"])
    execution_gold = executed and answer_equal(context.execution["result"], g["Gold_Answer"], g["Unit"])
    evidence_pass = conjunction([valid, predicted == expected_ids, checks["EvidenceValidator"], checks["FactExistenceValidator"], evidence_semantics])
    python_pass = conjunction([executed, execution_gold, checks["PythonResultValidator"], checks["EvidenceValidator"], checks["QuestionTypeValidator"], python_reasoning])
    type_pass = valid and artifact.question_type == g["Question_Type"]
    semantic_pass = conjunction([valid, semantic, checks["YearValidator"]])
    e2e = conjunction([semantic_pass, type_pass, evidence_pass, python_pass, answer_pass, unit_pass])
    return {"review_id": review_key(attempt), "run_id": attempt["run_id"], "question_id": attempt["question_id"],
            "run_index": attempt["run_index"], "condition": attempt["condition"], "attempt": attempt["attempt"],
            "question_type": g["Question_Type"], "artifact_hash": attempt.get("artifact_hash"),
            "schema_accuracy": int(valid), "semantic_parsing_accuracy": semantic_pass,
            "question_type_accuracy": int(type_pass), **metrics, "evidence_accuracy": evidence_pass,
            "python_accuracy": python_pass, "answer_accuracy": int(answer_pass), "unit_accuracy": int(unit_pass),
            "python_execution_rate": int(executed), "python_answer_consistency": int(checks["PythonResultValidator"]),
            "e2e": e2e, "review_pending": review is None and valid,
            "offline_failure_codes": sorted({str(i.failure_code) for v in validations for i in v.issues}),
            "offline_validator_results": {v.validator_name: v.model_dump(mode="json") for v in validations},
            "online_final_status": attempt["final_status"]}


def mean_complete(values):
    values = list(values)
    return statistics.mean(values) if values and all(v is not None for v in values) else None


def aggregate_run(first: list[dict], final: list[dict]) -> dict:
    n = len(final)
    metrics = {key: mean_complete(r[key] for r in final) for key in (
        "semantic_parsing_accuracy", "question_type_accuracy", "evidence_precision", "evidence_recall", "evidence_f1",
        "answer_accuracy", "python_execution_rate", "python_answer_consistency", "unit_accuracy", "evidence_accuracy", "python_accuracy")}
    tp, fp, fn = (sum(r[key] for r in final) for key in ("evidence_tp", "evidence_fp", "evidence_fn"))
    metrics.update(evidence_micro_precision=tp / (tp + fp) if tp + fp else 0.0,
                   evidence_micro_recall=tp / (tp + fn) if tp + fn else None,
                   evidence_micro_f1=2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0)
    first_map = {r["question_id"]: r for r in first}
    all_reviewed = all(r["e2e"] is not None for r in first + final)
    first_wrong = sum(r["e2e"] == 0 for r in first) if all_reviewed else None
    recovered = sum(first_map[r["question_id"]]["e2e"] == 0 and r["e2e"] == 1 for r in final) if all_reviewed else None
    metrics.update(question_count=n, e2e_accuracy=mean_complete(r["e2e"] for r in final),
                   first_pass_accuracy=mean_complete(r["e2e"] for r in first), final_accuracy=mean_complete(r["e2e"] for r in final),
                   recovery_rate=recovered / first_wrong if first_wrong else None,
                   recovery_numerator=recovered, recovery_denominator=first_wrong,
                   pending_reviews=sum(r["review_pending"] for r in final),
                   accepted_rate=sum(r["online_final_status"] == "ACCEPTED" for r in final) / n if n else None)
    return metrics


def evaluate_experiment(directory: Path, gold_rows: list[dict], questions: list[dict], facts, rules,
                        output: Path, reviews: list[dict] | None = None) -> dict:
    manifest = read_json(directory / "manifest.json")
    if manifest["experiment_kind"] != "main":
        raise ValueError("Scope and main experiment metrics must not be mixed")
    labels = {}
    for review in reviews or []:
        if review["review_id"] in labels:
            raise ValueError("Duplicate independent review ID")
        labels[review["review_id"]] = review
    gold_map = {r["question_id"]: r for r in gold_rows}
    question_map = {q["question_id"]: q for q in questions}
    expected = {(r["run_index"], r["condition"], r["question_id"]) for r in manifest["expected_runs"]}
    if len(expected) != len(manifest["expected_runs"]):
        raise ValueError("Duplicate expected runs")
    observed = set()
    scores, queue, failure_counts = [], [], Counter()
    firsts, finals = defaultdict(list), defaultdict(list)
    for run_index in (1, 2, 3):
        for condition in "ABCD":
            store = TraceStore(directory / f"run_{run_index:02d}" / condition)
            attempts = store.read("attempts")
            terminal = store.read("finals")
            by_question = defaultdict(list)
            for attempt in attempts:
                if attempt["condition"] != condition or attempt["run_index"] != run_index:
                    raise ValueError("Trace path/identity mismatch")
                by_question[attempt["question_id"]].append(attempt)
                failure_counts.update((condition, code, "online") for code in attempt["failure_codes"])
            for final in terminal:
                key = (run_index, condition, final["question_id"])
                if key in observed or key not in expected:
                    raise ValueError("Duplicate or unexpected final record")
                observed.add(key)
                rows = by_question[final["question_id"]]
                if not rows or [r["attempt"] for r in rows] != list(range(1, len(rows) + 1)):
                    raise ValueError("Missing or duplicate attempts")
                if len(rows) > (1 if condition in "AB" else 3):
                    raise ValueError("Attempt limit exceeded")
                if rows[-1]["record_hash"] != final["attempt_record_hash"] or final["artifact_hash"] != rows[-1]["artifact_hash"] or final["artifact"] != rows[-1]["artifact"]:
                    raise ValueError("Final does not reference its terminal attempt")
                gold = gold_map[final["question_id"]]
                question = question_map[gold["public_question_id"]]
                relevant = [rows[0]] if len(rows) == 1 else [rows[0], rows[-1]]
                scored = []
                for attempt in relevant:
                    if attempt.get("artifact_hash") != (digest(attempt["artifact"]) if attempt.get("artifact") is not None else None):
                        raise ValueError("Artifact hash mismatch")
                    score = score_attempt(attempt, gold, question, facts, rules, labels.get(review_key(attempt)))
                    scores.append(score)
                    scored.append(score)
                    failure_counts.update((condition, code, "offline") for code in score["offline_failure_codes"])
                    if score["review_pending"]:
                        queue.append({"review_id": score["review_id"], "artifact_hash": attempt["artifact_hash"],
                                      "question": question["question"], "generated_artifact": attempt["artifact"],
                                      "reference": {"time": gold["question_bank"]["Time"], "concept": gold["question_bank"]["Concept"],
                                                    "filter": gold["question_bank"]["Filter"], "logic": gold["question_bank"]["Logic"],
                                                    "golden_context": gold["gold_annotation"]["Golden_Context"],
                                                    "python_solution": gold["gold_annotation"]["Python_Solution"]},
                                      "reviewer": "", **{k: None for k in REVIEW_FIELDS}})
                firsts[run_index, condition].append(scored[0])
                finals[run_index, condition].append(scored[-1])
    if observed != expected:
        raise ValueError(f"Incomplete experiment: missing {len(expected - observed)} of {len(expected)} question-runs")
    used_review_ids = {s["review_id"] for s in scores}
    if set(labels) - used_review_ids:
        raise ValueError("Review IDs do not belong to these immutable artifacts")
    per_run = [{"run_index": run, "condition": condition, **aggregate_run(firsts[run, condition], rows)}
               for (run, condition), rows in sorted(finals.items())]
    by_type = [{"run_index": run, "condition": condition, "question_type": kind,
                **aggregate_run([r for r in firsts[run, condition] if r["question_type"] == kind],
                                [r for r in rows if r["question_type"] == kind])}
               for (run, condition), rows in sorted(finals.items()) for kind in sorted({r["question_type"] for r in rows})]
    aggregate = {}
    for condition in "ABCD":
        entries = [r for r in per_run if r["condition"] == condition]
        aggregate[condition] = {}
        if not entries:
            continue
        for key in entries[0]:
            if key in ("condition", "run_index"):
                continue
            values = [r[key] for r in entries]
            complete = all(v is not None for v in values)
            aggregate[condition][key] = {"per_run": values, "mean": statistics.mean(values) if complete else None,
                                         "sample_sd": statistics.stdev(values) if complete and len(values) > 1 else None}
    output.mkdir(parents=True, exist_ok=False)
    write_new_jsonl(output / "per_question.jsonl", scores)
    # Stable opaque ordering prevents the condition/run traversal from leaking into blind review.
    write_new_jsonl(output / "review_queue.jsonl", sorted(queue, key=lambda row: row["review_id"]))
    write_new_jsonl(output / "per_type_metrics.jsonl", by_type)
    with (output / "per_run_metrics.csv").open("x", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(per_run[0]))
        writer.writeheader()
        writer.writerows(per_run)
    with (output / "failure_analysis.csv").open("x", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["condition", "failure_code", "phase", "count"])
        writer.writerows([*key, count] for key, count in sorted(failure_counts.items()))
    summary = {"experiment_kind": "main", "mode": manifest["mode"], "expected_question_runs": len(expected),
               "observed_question_runs": len(observed), "pending_review_count": len(queue), "metrics": aggregate,
               "evaluated_at": timestamp(), "review_labels_hash": digest(reviews or []),
               "rules_hash": digest(rules), "experiment_manifest_hash": digest(manifest)}
    write_new_json(output / "aggregate_metrics.json", summary)
    lines = ["# Financial Annotation Evaluation", "", f"Mode: **{manifest['mode']}**. Question-runs: {len(observed)}/{len(expected)}.",
             f"Pending independent reviews: {len(queue)}. Null metrics are not zero.", "",
             "| Condition | E2E mean | First-pass mean | Recovery mean |", "|---|---:|---:|---:|"]
    for condition, values in aggregate.items():
        if values:
            lines.append(f"| {condition} | {values['e2e_accuracy']['mean']} | {values['first_pass_accuracy']['mean']} | {values['recovery_rate']['mean']} |")
    lines += ["", "Only independently adjudicated components determine semantic correctness; online Judge PASS is not a Gold score.",
              "FAILED outputs remain in the denominator. Scripted/demo results are software tests, not model-performance evidence."]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def evaluate_scope(records: list[dict]) -> dict:
    if not records or len({r["question_id"] for r in records}) != len(records):
        raise ValueError("Scope evaluation requires unique, nonempty labeled records")
    tp = fp = fn = tn = unsupported = failures = correct = 0
    for r in records:
        if type(r.get("gold_out_of_scope")) is not bool or r.get("status") not in ("OUT_OF_SCOPE", "ANSWERED", "FAILED"):
            raise ValueError("Invalid scope evaluation record")
        gold, predicted = r["gold_out_of_scope"], r["status"] == "OUT_OF_SCOPE"
        if r["status"] == "FAILED":
            failures += 1
        else:
            correct += int(gold == predicted)
        if gold and predicted: tp += 1
        elif gold: fn += 1
        elif predicted: fp += 1
        elif r["status"] != "FAILED": tn += 1
        unsupported += bool(gold and r.get("answer") is not None)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    return {"experiment_kind": "scope", "n": len(records), "tp": tp, "fp": fp, "fn": fn, "tn": tn, "failed_count": failures,
            "scope_detection_accuracy": correct / len(records), "precision": precision, "recall": recall,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
            "unsupported_answer_rate": unsupported / len(records),
            "warning": "No in-scope negatives: false-positive performance is unmeasured" if tp + fn == len(records) else None}
