"""Synthetic software demonstration, deliberately unrelated to the UMC Gold."""

from __future__ import annotations

import json
from pathlib import Path

from .config import Settings
from .evaluation import REVIEW_FIELDS, evaluate_experiment, review_key
from .facts import FactRepository, create_database
from .io_utils import digest, write_new_json, write_new_jsonl
from .model_client import ScriptedClient, Turn
from .runner import AnnotationRunner
from .schemas import QuestionInput
from .trace import TraceStore


def demo_data():
    source = {"sha256": digest("synthetic-demo-v1"), "description": "Synthetic fixture, not research observations"}
    facts = []
    for year, value in ((2024, "100"), (2025, "120")):
        facts.append({"fact_id": f"SYN_{year}_revenue", "source_id": source["sha256"], "company": "Synthetic Co",
                      "stock_code": "SYN", "fiscal_year": year, "roc_year": year - 1911,
                      "statement": "income_statement", "statement_raw": "簡明綜合損益表", "concept_id": "revenue", "concept_zh": "營業收入",
                      "value_decimal": value, "value_status": "reported", "unit": "TWD_thousand", "unit_raw": "新臺幣仟元",
                      "period_type": "duration", "period_start": f"{year}-01-01", "period_end": f"{year}-12-31",
                      "source_description": "Synthetic test fixture", "source_sheet": "synthetic", "source_row": year - 2023,
                      "source_value_cell": "A1"})
    question = QuestionInput(question_id="Q_synthetic", question="2025年度營業收入相較2024年度的成長率為何？", language="zh")
    artifact = {"question_id": question.question_id,
                "semantic_parse": {"time": [{"fiscal_year": y, "period_type": "duration", "period_start": f"{y}-01-01", "period_end": f"{y}-12-31"} for y in (2024, 2025)],
                                   "concept": ["營業收入"], "filter": [], "logic": "(new-old)/old"},
                "question_type": "Growth_Rate", "retrieved_fact_ids": [f["fact_id"] for f in facts],
                "selected_evidence": [{"fact_id": f["fact_id"], "value": f["value_decimal"], "unit": f["unit"],
                                       "variable_name": f"revenue_{f['fiscal_year']}", "index_key": None} for f in facts],
                "golden_context": "## 簡明綜合損益表\n| 項目 | 2024 | 2025 |\n| --- | ---: | ---: |\n| 營業收入 | 100 | 120 |\n來源單位：新臺幣仟元",
                "python_solution": "def solution():\n    revenue_2024 = 100\n    revenue_2025 = 120\n    growth = (revenue_2025 - revenue_2024) / revenue_2024\n    return round(growth * 100, 2)",
                "answer": 20.0, "unit": "percent"}
    gold = {"question_id": "SYN01", "public_question_id": question.question_id,
            "question_bank": {"Time": "2024至2025年度", "Concept": "營業收入", "Filter": None, "Logic": "(new-old)/old"},
            "gold_annotation": {"Question_Type": "Growth_Rate", "Gold_Answer": 20.0, "Unit": "%",
                                "Source_Fact_IDs": "; ".join(artifact["retrieved_fact_ids"]),
                                "Golden_Context": artifact["golden_context"], "Python_Solution": artifact["python_solution"]}}
    return source, facts, question, artifact, gold


def search_turn(call_id="lookup"):
    return Turn(tool_calls=[{"id": call_id, "type": "function", "function": {"name": "search_financial_facts", "arguments": json.dumps({"query": "營業收入", "years": [2024, 2025]})}}], finish_reason="tool_calls")


def judge_pass():
    return Turn(content=json.dumps({"semantic_parse_pass": True, "concept_pass": True, "evidence_pass": True,
                                    "golden_context_pass": True, "overall_pass": True, "failure_codes": [], "issues": [], "feedback": ""}))


def run_demo(output: Path, rules: dict, prompts: dict) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    source, facts, question, artifact, gold = demo_data()
    create_database(output / "financial_facts.sqlite", facts, source)
    repo = FactRepository(output / "financial_facts.sqlite")
    settings = Settings()
    expected = [{"run_index": r, "condition": c, "question_id": "SYN01"} for r in (1, 2, 3) for c in "ABCD"]
    write_new_json(output / "manifest.json", {"experiment_kind": "main", "mode": "synthetic_demo", "expected_runs": expected,
                                               "settings": settings.model_dump(), "rules_hash": digest(rules)})
    reviews = []
    for row in expected:
        condition, index = row["condition"], row["run_index"]
        wrong = {**artifact, "answer": 99.0}
        turns = [search_turn(), Turn(content=json.dumps(wrong))]
        if condition in "CD":
            turns.append(Turn(content=json.dumps(artifact)))
        if condition == "D":
            turns.append(judge_pass())
        client = ScriptedClient(turns)
        with TraceStore(output / f"run_{index:02d}" / condition) as store:
            runner = AnnotationRunner(settings, repo, rules, prompts, client, store)
            runner.run_question(question, source_question_id="SYN01", condition=condition, run_index=index, experiment_id=output.name)
            for attempt in store.read("attempts"):
                reviews.append({"review_id": review_key(attempt), "artifact_hash": attempt["artifact_hash"],
                                "reviewer": "synthetic-fixture-oracle (NOT a human research review)", **{k: True for k in REVIEW_FIELDS}})
    write_new_jsonl(output / "synthetic_reviews.jsonl", reviews)
    write_new_jsonl(output / "synthetic_gold.jsonl", [gold])
    return evaluate_experiment(output, [gold], [question.model_dump()], repo, rules, output / "evaluation", reviews)

