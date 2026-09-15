import copy

import pytest

from financial_annotation_harness.schemas import Annotation
from financial_annotation_harness.validators import ValidationContext, all_pass, answer_equal, question_years, validate_all


def validate(specimen, rules, artifact=None):
    repo, q, a, _ = specimen
    context = ValidationContext(q.question_id, q.question, repo, rules, set(a["retrieved_fact_ids"]))
    _, checks = validate_all(a if artifact is None else artifact, context)
    return checks


def codes(checks):
    return {str(i.failure_code) for check in checks for i in check.issues}


def test_valid_grounded_growth(specimen, rules):
    checks = validate(specimen, rules)
    assert all_pass(checks), checks


@pytest.mark.parametrize("field,value,expected", [
    ("answer", 99, "PYTHON_ANSWER_MISMATCH"),
    ("unit", "TWD_thousand", "UNIT_ERROR"),
    ("question_type", "Single-Fact", "QUESTION_TYPE_ERROR"),
    ("question_id", "wrong-id", "SCHEMA_ERROR"),
    ("python_solution", "def solution():\n    return open('x')", "PYTHON_EXECUTION_ERROR"),
    ("golden_context", "No evidence", "EVIDENCE_ERROR"),
])
def test_independent_failure_codes(specimen, rules, field, value, expected):
    bad = copy.deepcopy(specimen[2])
    bad[field] = value
    assert expected in codes(validate(specimen, rules, bad))


def test_schema_is_strict_and_no_repair(specimen, rules):
    bad = copy.deepcopy(specimen[2])
    bad["semantic_parse"]["time"][0]["fiscal_year"] = "2024"
    assert codes(validate(specimen, rules, bad)) == {"SCHEMA_ERROR"}
    bad = copy.deepcopy(specimen[2])
    bad["extra"] = "not accepted"
    assert "SCHEMA_ERROR" in codes(validate(specimen, rules, bad))


def test_fact_context_and_grounding_mutations(specimen, rules):
    bad = copy.deepcopy(specimen[2])
    bad["selected_evidence"][0]["value"] = "101"
    assert "EVIDENCE_ERROR" in codes(validate(specimen, rules, bad))
    bad = copy.deepcopy(specimen[2])
    bad["golden_context"] = bad["golden_context"].replace("| 100 |", "| 101 |")
    assert "EVIDENCE_ERROR" in codes(validate(specimen, rules, bad))
    bad = copy.deepcopy(specimen[2])
    bad["python_solution"] = bad["python_solution"].replace("return round(growth * 100, 2)", "return 20")
    assert "EVIDENCE_ERROR" in codes(validate(specimen, rules, bad))
    bad = copy.deepcopy(specimen[2])
    bad["selected_evidence"][0]["fact_id"] = "invented"
    assert "EVIDENCE_ERROR" in codes(validate(specimen, rules, bad))


def test_wrong_year_and_formula(specimen, rules):
    bad = copy.deepcopy(specimen[2])
    bad["semantic_parse"]["time"].pop()
    assert "YEAR_ERROR" in codes(validate(specimen, rules, bad))
    bad = copy.deepcopy(specimen[2])
    bad["python_solution"] = bad["python_solution"].replace("/ revenue_2024", "/ revenue_2025")
    bad["answer"] = 16.67
    assert "FORMULA_ERROR" in codes(validate(specimen, rules, bad))


def test_c_has_no_semantic_oracle(specimen, rules):
    # Mechanically consistent but semantically wrong parse: C must not pretend to judge it.
    bad = copy.deepcopy(specimen[2])
    bad["semantic_parse"]["concept"] = ["資產總計"]
    checks = validate(specimen, rules, bad)
    assert all_pass(checks)
    assert "CONCEPT_ERROR" not in codes(checks)


@pytest.mark.parametrize("question,years", [("112至114年度", {2023, 2024, 2025}),
                                           ("112與114年", {2023, 2025}),
                                           ("from 2023 to 2025", {2023, 2024, 2025}),
                                           ("40%的比例", set())])
def test_explicit_year_normalization(question, years):
    assert question_years(question) == years


def test_answer_comparison_rules():
    assert answer_equal(114, 2025, "year")
    assert answer_equal("是", "Yes", "boolean")
    assert answer_equal(3.80, 3.8, "TWD")
    assert not answer_equal(0.02, 2, "percent")
    assert not answer_equal(True, 1, "TWD_thousand")
    assert not answer_equal(None, None, "TWD")


@pytest.mark.parametrize("kind,code,answer,unit", [
    ("Comparison", "def solution():\n    revenue_by_year = {2024: 100, 2025: 120}\n    return max(revenue_by_year, key=revenue_by_year.get)", 2025, "year"),
    ("Logic", "def solution():\n    revenue_2024 = 100\n    revenue_2025 = 120\n    return 'Yes' if revenue_2025 > revenue_2024 else 'No'", "Yes", "boolean"),
    ("Arithmetic", "def solution():\n    revenue_2024 = 100\n    revenue_2025 = 120\n    total = revenue_2024 + revenue_2025\n    return total", 220, "TWD_thousand"),
])
def test_other_primary_types(specimen, rules, kind, code, answer, unit):
    artifact = copy.deepcopy(specimen[2])
    artifact.update(question_type=kind, python_solution=code, answer=answer, unit=unit)
    if kind == "Comparison":
        for e, year in zip(artifact["selected_evidence"], [2024, 2025]):
            e.update(variable_name="revenue_by_year", index_key=year)
    checks = validate(specimen, rules, artifact)
    assert all_pass(checks), checks


def test_single_fact_supported(specimen, rules):
    repo, question, good, _ = specimen
    a = copy.deepcopy(good)
    a.update(question_type="Single-Fact", retrieved_fact_ids=[good["retrieved_fact_ids"][1]], selected_evidence=[good["selected_evidence"][1]],
             golden_context="| 項目 | 2025 |\n| --- | ---: |\n| 營業收入 | 120 |\n來源單位：新臺幣仟元",
             python_solution="def solution():\n    revenue_2025 = 120\n    return revenue_2025", answer=120, unit="TWD_thousand")
    a["semantic_parse"]["time"] = a["semantic_parse"]["time"][1:]
    context = ValidationContext(question.question_id, "2025年營業收入是多少", repo, rules, set(good["retrieved_fact_ids"]))
    _, checks = validate_all(a, context)
    assert all_pass(checks), checks


def test_ratio_with_two_distinct_concepts(tmp_path, rules):
    from financial_annotation_harness.demo import demo_data
    from financial_annotation_harness.facts import FactRepository, create_database
    source, facts, q, artifact, _ = demo_data()
    facts[0].update(fact_id="SYN_2025_cost", fiscal_year=2025, roc_year=114, concept_id="cost", concept_zh="營業成本",
                    period_start="2025-01-01", period_end="2025-12-31", value_decimal="60")
    create_database(tmp_path / "ratio.sqlite", facts, source)
    repo = FactRepository(tmp_path / "ratio.sqlite")
    artifact.update(question_type="Ratio", retrieved_fact_ids=[f["fact_id"] for f in facts],
        selected_evidence=[{"fact_id": f["fact_id"], "value": f["value_decimal"], "unit": f["unit"], "variable_name": name, "index_key": None}
                           for f, name in zip(facts, ["cost", "revenue"])],
        golden_context="| 項目 | 2025 |\n| --- | ---: |\n| 營業成本 | 60 |\n| 營業收入 | 120 |\n來源單位：新臺幣仟元",
        python_solution="def solution():\n    cost = 60\n    revenue = 120\n    return round(cost / revenue * 100, 2)", answer=50.0)
    artifact["semantic_parse"]["time"] = artifact["semantic_parse"]["time"][1:]
    context = ValidationContext(q.question_id, "2025年營業成本占營業收入百分比？", repo, rules, set(artifact["retrieved_fact_ids"]))
    _, checks = validate_all(artifact, context)
    assert all_pass(checks), checks


def test_null_fact_blocked_not_zero(tmp_path, rules):
    from financial_annotation_harness.demo import demo_data
    from financial_annotation_harness.facts import FactRepository, create_database
    source, facts, q, artifact, _ = demo_data()
    facts[0].update(value_decimal=None, value_status="not_reported")
    create_database(tmp_path / "null.sqlite", facts, source)
    context = ValidationContext(q.question_id, q.question, FactRepository(tmp_path / "null.sqlite"), rules, set(artifact["retrieved_fact_ids"]))
    _, checks = validate_all(artifact, context)
    assert "EVIDENCE_ERROR" in codes(checks)


def test_context_unit_must_match_exactly(specimen, rules):
    artifact = copy.deepcopy(specimen[2])
    artifact["golden_context"] = artifact["golden_context"].replace("新臺幣仟元", "元")
    assert "UNIT_ERROR" in codes(validate(specimen, rules, artifact))
