from collections import Counter

import pytest

from financial_annotation_harness.dataset import derive_dataset, inspect_dataset, public_id, stratified_split, verify_derived
from financial_annotation_harness.io_utils import file_hash, read_jsonl
from financial_annotation_harness.schemas import QUESTION_TYPES


def metadata():
    return [{"question_id": f"{kind}_{i}", "question_type": kind} for kind in QUESTION_TYPES for i in range(10)]


def test_split_independent_of_row_order():
    a = stratified_split(metadata(), "hash")
    b = stratified_split(list(reversed(metadata())), "hash")
    assert a == b
    assert len(a["development"]) == 12 and len(a["test"]) == 48
    assert not set(a["development"]) & set(a["test"])
    assert all(len(g["development"]) == 2 and len(g["test"]) == 8 for g in a["groups"].values())
    assert stratified_split(metadata(), "hash", 777) != a


def test_split_rejects_missing_and_duplicate():
    with pytest.raises(ValueError):
        stratified_split(metadata()[:-1], "hash")
    with pytest.raises(ValueError):
        stratified_split(metadata() + [metadata()[0]], "hash")


def test_public_ids_do_not_disclose_question_type():
    ids = [public_id(m["question_id"]) for m in metadata()]
    assert len(set(ids)) == 60
    assert all(i.startswith("Q_") and len(i) == 18 for i in ids)


def test_source_audit_and_read_only_derivation(root, tmp_path):
    source = root / "data/financial_qa_gold_dataset_v2.xlsx"
    before = file_hash(source)
    report = inspect_dataset(source)["report"]
    assert report["errors"] == []
    assert report["fact_count"] == 138
    assert report["value_status_counts"] == {"reported": 99, "not_reported": 33, "reported_zero": 6}
    assert "GOLD-02" in report["rule_ids"]
    out = derive_dataset(source, tmp_path / "artifacts")
    assert file_hash(source) == before
    assert derive_dataset(source, tmp_path / "artifacts") == out
    inputs = read_jsonl(out / "question_inputs.jsonl")
    assert len(inputs) == 60
    assert all(set(q) == {"question_id", "zh", "en"} for q in inputs)
    assert len(read_jsonl(out / "gold_annotations.jsonl")) == 60
    (out / "question_inputs.jsonl").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact changed"):
        verify_derived(source, out)

