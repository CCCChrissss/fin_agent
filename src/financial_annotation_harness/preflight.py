"""Offline readiness checks for the Development experiment."""

from __future__ import annotations

from pathlib import Path

from .config import load_settings
from .dataset import stratified_split, verify_derived
from .governance import validate_selection
from .io_utils import file_hash, read_json, read_jsonl


def dev_preflight(root: Path, config_path: Path, review_report: dict | None = None) -> dict:
    source = root / "data/financial_qa_gold_dataset_v2.xlsx"
    derived = root / "artifacts/derived" / file_hash(source)
    source_manifest = verify_derived(source, derived)
    metadata = read_jsonl(derived / "question_metadata.jsonl")
    split = read_json(root / "artifacts/dataset_split.json")
    if split != stratified_split(metadata, source_manifest["sha256"], split["seed"]):
        raise ValueError("Dataset split is not reproducible")
    settings = load_settings(config_path)
    if settings.split_seed != split["seed"]:
        raise ValueError("Config and split seed differ")
    if settings.conditions != ["A", "B", "C", "D"] or settings.runs_per_condition != 3 or settings.max_retries != 2:
        raise ValueError("A/B/C/D experiment controls differ from protocol")
    if settings.model.generator_model != settings.model.judge_model or settings.model.generator_version != settings.model.judge_version:
        raise ValueError("Generator and Judge must use the selected same model/version")
    selection_hash = validate_selection(root, settings)
    blockers = [] if review_report and review_report.get("status") == "COMPLETE" else ["gold_rules_judge_review"]
    return {
        "schema_version": "1.0", "status": "READY" if not blockers else "BLOCKED_HUMAN_REVIEW",
        "partition": "development", "question_count": len(split["development"]),
        "expected_question_runs": len(split["development"]) * 4 * 3,
        "conditions": settings.conditions, "runs_per_condition": settings.runs_per_condition,
        "max_retries": settings.max_retries, "generator_model": settings.model.generator_model,
        "judge_model": settings.model.judge_model, "model_digest": settings.model.generator_version,
        "selection_hash": selection_hash, "source_verified": True, "split_verified": True,
        "no_model_requests": True, "live_execution_enabled": settings.max_live_calls > 0,
        "blockers": blockers,
    }

