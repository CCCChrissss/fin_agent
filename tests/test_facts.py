import sqlite3

import pytest

from financial_annotation_harness.demo import demo_data
from financial_annotation_harness.facts import FactRepository, create_database


def test_search_filters_order_and_limit(specimen):
    repo, *_ = specimen
    full = repo.search_financial_facts("營業收入")
    assert [x["year"] for x in full["candidates"]] == [2024, 2025]
    small = repo.search_financial_facts("revenue", top_k=1)
    assert small["truncated"] and small["total_matches"] == 2
    assert len(small["candidates"]) == 1
    assert repo.search_financial_facts("revenue", years=[2025])["candidates"][0]["value"] == "120"
    assert repo.search_financial_facts("revenue", statement_type="balance_sheet")["candidates"] == []
    assert repo.search_financial_facts("' OR 1=1 --")["candidates"] == []


def test_missing_is_not_zero(tmp_path):
    source, facts, *_ = demo_data()
    facts[0].update(value_decimal=None, value_status="not_reported")
    facts[1].update(value_decimal="0", value_status="reported_zero")
    path = tmp_path / "null.sqlite"
    create_database(path, facts, source)
    answer = FactRepository(path).search_financial_facts("revenue")
    assert answer["candidates"][0]["value"] is None
    assert answer["candidates"][1]["value"] == "0"
    assert answer["missing_information"] == [{"kind": "not_reported", "fact_id": facts[0]["fact_id"]}]


def test_db_is_read_only_and_no_gold(specimen):
    repo, *_ = specimen
    with repo.connect() as conn:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM financial_facts")
    with sqlite3.connect(repo.path) as conn:
        conn.execute("CREATE TABLE gold_answers (answer TEXT)")
    with pytest.raises(ValueError, match="Gold"):
        FactRepository(repo.path)


@pytest.mark.parametrize("kwargs", [{"top_k": 0}, {"years": ["2025"]}, {"statement_type": "cash_flow"}, {"query": ""}])
def test_invalid_search_arguments(specimen, kwargs):
    with pytest.raises(ValueError):
        specimen[0].search_financial_facts(**{"query": "revenue", **kwargs})

