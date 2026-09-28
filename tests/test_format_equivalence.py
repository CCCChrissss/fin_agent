"""Equivalent rendering must not weaken financial or binding checks."""
import copy
from decimal import Decimal

import pytest

from financial_annotation_harness.schemas import Annotation
from financial_annotation_harness.validators import (
    EvidenceValidator, UnitValidator, ValidationContext, context_facts,
)


@pytest.mark.parametrize("label", ["單位：TWD_thousand", "來源單位：新台幣千元", "Unit: TWD_thousand"])
def test_explicit_equivalent_source_units(specimen, rules, label):
    repo, q, good, _ = specimen
    artifact = copy.deepcopy(good)
    artifact["golden_context"] = artifact["golden_context"].split("來源單位")[0] + label
    check = UnitValidator().validate(Annotation.model_validate(artifact), ValidationContext(q.question_id, q.question, repo, rules))
    assert check.status == "PASS", check


@pytest.mark.parametrize("label", ["", "單位：元", "單位：TWD_thousand\n來源單位：元", "單位：unknown"])
def test_missing_wrong_or_conflicting_source_units_fail(specimen, rules, label):
    repo, q, good, _ = specimen
    artifact = copy.deepcopy(good)
    artifact["golden_context"] = artifact["golden_context"].split("來源單位")[0] + label
    check = UnitValidator().validate(Annotation.model_validate(artifact), ValidationContext(q.question_id, q.question, repo, rules))
    assert "UNIT-05" in {i.rule_id for i in check.issues}


@pytest.mark.parametrize("table", [
    "項目 | 2024 | 2025\n--- | ---: | ---:\n營業收入 | 100 | 120",
    "| 項目 | 2024 | 2025 |\n--- | --- | ---\n營業收入 | 100 | 120 |",
])
def test_optional_table_borders_preserve_cells(table):
    assert context_facts(table) == [("營業收入", 2024, Decimal("100")), ("營業收入", 2025, Decimal("120"))]


@pytest.mark.parametrize("table", [
    "項目 | 2024 | 2025\n營業收入 | 100 | 120",
    "項目 | 2024 | 2025\n--- | ---\n營業收入 | 100 | 120",
    "項目 | 2024 | 2025\n--- | --- | ---\n營業收入 | 100",
    "項目 | 2024\n--- | ---\n營業收入 | NaN",
])
def test_optional_border_tables_still_require_structure_and_finite_values(table):
    with pytest.raises(ValueError):
        context_facts(table)


def test_equivalent_table_keeps_exact_values_and_scalar_binding(specimen, rules):
    repo, q, good, _ = specimen
    artifact = copy.deepcopy(good)
    artifact["golden_context"] = "項目 | 2024 | 2025\n--- | --- | ---\n營業收入 | 101 | 120"
    context = ValidationContext(q.question_id, q.question, repo, rules, execution={"success": True, "locals": {"revenue_2024": 100, "revenue_2025": 120}})
    artifact["selected_evidence"][0]["index_key"] = 2024
    check = EvidenceValidator().validate(Annotation.model_validate(artifact), context)
    assert {"GOLD-01", "POT-01"} <= {i.rule_id for i in check.issues}
