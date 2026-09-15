"""Read-only source import and reproducible splits. No model access."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from pathlib import Path

import openpyxl

from .facts import STATEMENT_MAP, UNIT_MAP, create_database
from .io_utils import digest, file_hash, read_json, timestamp, write_new_json, write_new_jsonl
from .schemas import QUESTION_TYPES

BANK_COLUMNS = "Question_ID Question_Type Difficulty Chinese_Question English_Question Time Concept Filter Logic Required_Items Years Unit Template Scope_Status Question_Source Review_Status Notes".split()
FACT_COLUMNS = "Fact_ID Company Stock_Code Fiscal_Year ROC_Year Statement Concept_ID Concept_ZH Value Value_Status Unit Period_Type Period_Start Period_End Source".split()
GOLD_COLUMNS = "Question_ID Question_Type Difficulty Chinese_Question English_Question Golden_Context Python_Solution Gold_Answer Answer_Display_ZH Unit Source_Fact_IDs Execution_Result Required_Facts_Pass Null_Check Unit_Check Type_Logic_Check Golden_Context_Check Python_Execution_Pass Answer_Match Validation_Status Validation_Notes".split()


def read_table(workbook, sheet: str, columns: list[str], header_row: int = 4) -> list[dict]:
    rows = list(workbook[sheet].values)
    if list(rows[header_row - 1][:len(columns)]) != columns:
        raise ValueError(f"Unexpected schema: {sheet}")
    result = []
    for row_index, row in enumerate(rows[header_row:], header_row + 1):
        if not row or not any(v is not None for v in row):
            continue
        if not row[0]:
            raise ValueError(f"Record without ID: {sheet}:{row_index}")
        result.append({**dict(zip(columns, row)), "_row": row_index})
    return result


def public_id(original: str) -> str:
    return "Q_" + digest(["public-question-v1", original])[:16]


def inspect_dataset(path: Path) -> dict:
    path = path.resolve(strict=True)
    before = file_hash(path)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=False)
    try:
        bank = read_table(wb, "01_Question_Bank", BANK_COLUMNS)
        facts = read_table(wb, "02_Financial_Facts", FACT_COLUMNS)
        gold = read_table(wb, "06_Gold_Annotations", GOLD_COLUMNS)
        rule_rows = list(wb["04_Validation_Rules"].values)
        rules = [list(r[:7]) for r in rule_rows[3:] if r and r[0]]
        sheets = [{"name": s.title, "rows": len(list(s.values))} for s in wb]
    finally:
        wb.close()
    if file_hash(path) != before:
        raise ValueError("Source changed during read")
    errors = []
    for rows, key in ((bank, "Question_ID"), (gold, "Question_ID"), (facts, "Fact_ID")):
        if len({x[key] for x in rows}) != len(rows):
            errors.append(f"Duplicate {key}")
    by_question = {x["Question_ID"]: x for x in bank}
    by_fact = {x["Fact_ID"]: x for x in facts}
    if set(by_question) != {x["Question_ID"] for x in gold}:
        errors.append("Question/Gold IDs do not match")
    counts = Counter(x["Question_Type"] for x in bank)
    if counts != Counter({t: 10 for t in QUESTION_TYPES}):
        errors.append("Expected exactly 10 questions per type")
    for f in facts:
        if f["Fiscal_Year"] != f["ROC_Year"] + 1911 or f["Statement"] not in STATEMENT_MAP:
            errors.append(f"Fact year/statement: {f['Fact_ID']}")
        status, value = f["Value_Status"], f["Value"]
        valid = (status == "not_reported" and value is None or
                 status == "reported_zero" and value == 0 or
                 status == "reported" and value is not None and value != 0)
        if not valid:
            errors.append(f"Null/zero status: {f['Fact_ID']}")
        if f["Unit"] not in UNIT_MAP:
            errors.append(f"Unknown unit: {f['Fact_ID']}")
        expected_type = "instant" if f["Statement"] == "簡明資產負債表" else "duration"
        year = f["Fiscal_Year"]
        if (f["Period_Type"] != expected_type or f["Period_End"] != f"{year}-12-31" or
                f["Period_Start"] != (f"{year}-01-01" if expected_type == "duration" else None)):
            errors.append(f"Period mismatch: {f['Fact_ID']}")
    for g in gold:
        q = by_question.get(g["Question_ID"])
        if q is None:
            continue
        for key in ("Question_Type", "Difficulty", "Chinese_Question", "English_Question", "Unit"):
            if q[key] != g[key]:
                errors.append(f"Joined field mismatch: {g['Question_ID']}:{key}")
        ids = [i.strip() for i in g["Source_Fact_IDs"].split(";")]
        if any(i not in by_fact or by_fact[i]["Value"] is None for i in ids):
            errors.append(f"Missing reference: {g['Question_ID']}")
        expected = {(c.strip(), int(y.strip())) for c in q["Required_Items"].split("；") for y in q["Years"].split(",")}
        actual = {(by_fact[i]["Concept_ZH"], by_fact[i]["Fiscal_Year"]) for i in ids if i in by_fact}
        if expected != actual:
            errors.append(f"Required facts mismatch: {g['Question_ID']}")
        if g["Execution_Result"] != g["Gold_Answer"]:
            errors.append(f"Stored answer/result mismatch: {g['Question_ID']}")
    report = {"sha256": before, "sheets": sheets, "question_count": len(bank), "fact_count": len(facts),
              "gold_count": len(gold), "question_type_counts": dict(counts),
              "value_status_counts": dict(Counter(f["Value_Status"] for f in facts)),
              "rule_ids": [r[0] for r in rules], "errors": errors,
              "warnings": ["GOLD-02 is outside the named Excel Table; imported from the sheet.",
                           "Stored PASS flags are provenance, not newly executed validation.",
                           "Source screenshots are not part of this dataset."]}
    return {"report": report, "bank": bank, "facts": facts, "gold": gold, "rules": rules}


def verify_gold_python(path: Path, rules: dict) -> dict:
    """Source compatibility audit only; never use these results as model accuracy."""
    from .python_executor import execute_python
    from .validators import answer_equal

    data = inspect_dataset(path)
    results = []
    for row in data["gold"]:
        execution = execute_python(row["Python_Solution"], **rules["execution"])
        results.append({"question_id": row["Question_ID"], "execution_pass": execution["success"],
                        "answer_match": execution["success"] and answer_equal(execution["result"], row["Gold_Answer"], row["Unit"]),
                        "python_result": execution["result"], "error": execution["error"]})
    return {"purpose": "Gold reference Python execution compatibility; not a Generator experiment or semantic review",
            "source_sha256": data["report"]["sha256"], "question_count": len(results),
            "execution_pass_count": sum(r["execution_pass"] for r in results),
            "answer_match_count": sum(r["answer_match"] for r in results), "results": results}


def derive_dataset(path: Path, artifacts: Path) -> Path:
    data = inspect_dataset(path)
    report = data["report"]
    if report["errors"]:
        raise ValueError(report["errors"])
    out = artifacts.resolve() / "derived" / report["sha256"]
    if path.resolve() == out or path.resolve().is_relative_to(out):
        raise ValueError("Derived output must not contain or overwrite source")
    if out.exists():
        verify_derived(path, out)
        return out
    out.mkdir(parents=True)
    source = {"sha256": report["sha256"], "relative_path": "data/" + path.name,
              "source_version_label": "v2 (some sheet titles retain v1)", "importer_version": "1.0",
              "imported_at": timestamp()}
    facts = []
    for f in data["facts"]:
        facts.append({"fact_id": f["Fact_ID"], "source_id": source["sha256"], "company": f["Company"],
                      "stock_code": str(f["Stock_Code"]), "fiscal_year": f["Fiscal_Year"], "roc_year": f["ROC_Year"],
                      "statement": STATEMENT_MAP[f["Statement"]], "statement_raw": f["Statement"],
                      "concept_id": f["Concept_ID"], "concept_zh": f["Concept_ZH"],
                      "value_decimal": format(Decimal(str(f["Value"])), "f") if f["Value"] is not None else None,
                      "value_status": f["Value_Status"], "unit": UNIT_MAP[f["Unit"]], "unit_raw": f["Unit"],
                      "period_type": f["Period_Type"], "period_start": f["Period_Start"], "period_end": f["Period_End"],
                      "source_description": f["Source"], "source_sheet": "02_Financial_Facts", "source_row": f["_row"],
                      "source_value_cell": f"I{f['_row']}"})
    create_database(out / "financial_facts.sqlite", facts, source)
    by_question = {q["Question_ID"]: q for q in data["bank"]}
    inputs = []
    metadata = []
    for q in data["bank"]:
        public = public_id(q["Question_ID"])
        inputs.append({"question_id": public, "zh": q["Chinese_Question"], "en": q["English_Question"]})
        metadata.append({"question_id": q["Question_ID"], "public_question_id": public,
                         "question_type": q["Question_Type"], "difficulty": q["Difficulty"],
                         "review_status": q["Review_Status"], "source_row": q["_row"]})
    gold = [{"question_id": g["Question_ID"], "public_question_id": public_id(g["Question_ID"]),
             "question_bank": by_question[g["Question_ID"]], "gold_annotation": g} for g in data["gold"]]
    write_new_jsonl(out / "question_inputs.jsonl", inputs)
    write_new_jsonl(out / "question_metadata.jsonl", metadata)
    write_new_jsonl(out / "gold_annotations.jsonl", gold)
    write_new_json(out / "audit.json", report)
    write_new_json(out / "source_manifest.json", {**source, "facts_content_hash": digest(sorted(facts, key=lambda f: f["fact_id"])),
                     "files": {p.name: file_hash(p) for p in sorted(out.iterdir()) if p.is_file()}})
    verify_derived(path, out)
    return out


def verify_derived(source: Path, out: Path) -> dict:
    manifest = read_json(out / "source_manifest.json")
    if file_hash(source) != manifest["sha256"]:
        raise ValueError("Original Excel hash changed")
    required = {"financial_facts.sqlite", "question_inputs.jsonl", "question_metadata.jsonl", "gold_annotations.jsonl", "audit.json"}
    if set(manifest["files"]) != required:
        raise ValueError("Incomplete derived manifest")
    for name, expected in manifest["files"].items():
        if file_hash(out / name) != expected:
            raise ValueError(f"Derived artifact changed: {name}")
    return manifest


def stratified_split(metadata: list[dict], source_hash: str, seed: int = 20260915) -> dict:
    if len({m["question_id"] for m in metadata}) != len(metadata):
        raise ValueError("Duplicate question IDs")
    if Counter(m["question_type"] for m in metadata) != Counter({t: 10 for t in QUESTION_TYPES}):
        raise ValueError("Split requires exactly six types of ten questions")
    groups = {}
    for kind in QUESTION_TYPES:
        ordered = sorted((m for m in metadata if m["question_type"] == kind),
                         key=lambda m: (digest([seed, kind, m["question_id"]]), m["question_id"]))
        groups[kind] = {"development": [m["question_id"] for m in ordered[:2]],
                        "test": [m["question_id"] for m in ordered[2:]]}
    return {"schema_version": "1.0", "algorithm": "sha256-canonical-json-v1", "seed": seed,
            "source_sha256": source_hash, "groups": groups,
            "development": sorted(q for g in groups.values() for q in g["development"]),
            "test": sorted(q for g in groups.values() for q in g["test"])}
