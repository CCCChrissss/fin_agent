import copy
from pathlib import Path

import pytest
import yaml

from financial_annotation_harness.cli import safe_output
from financial_annotation_harness.config import ModelConfig, Settings, load_rules, load_settings
from financial_annotation_harness.dataset import stratified_split
from financial_annotation_harness.governance import create_freeze, verify_freeze
from financial_annotation_harness.schemas import QUESTION_TYPES


def live_settings():
    return Settings(model=ModelConfig(provider="openai", generator_model="model-snapshot", generator_version="model-snapshot",
                                     judge_model="judge-snapshot", judge_version="judge-snapshot"), max_live_calls=10)


def test_config_no_silent_retry_override(tmp_path, root, monkeypatch):
    monkeypatch.setenv("MAX_RETRIES", "5")
    with pytest.raises(ValueError, match="conflicts"):
        load_settings(root / "config/experiment.example.yaml")
    monkeypatch.delenv("MAX_RETRIES")
    path = tmp_path / "bad.yaml"
    path.write_text("max_retries: 3\n")
    with pytest.raises(ValueError):
        load_settings(path)
    path.write_text("unknown_key: ignored?\n")
    with pytest.raises(ValueError):
        load_settings(path)


def test_live_is_explicit_and_no_implicit_judge_fallback():
    with pytest.raises(ValueError):
        Settings().require_live()
    s = live_settings()
    s.require_live()
    s.model.judge_version = ""
    with pytest.raises(ValueError):
        s.require_live()


def test_freeze_rejects_changed_prompt(tmp_path):
    for name in ("pyproject.toml", "requirements.lock", "docs/experiment_protocol.md", "docs/research_context.md",
                 "docs/evaluation_rubric.md", "docs/implementation_design.md", "prompts/workflow.md"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("frozen fixture")
    rows = [{"question_id": f"{kind}{i}", "question_type": kind} for kind in QUESTION_TYPES for i in range(10)]
    split = stratified_split(rows, "sourcehash")
    settings = live_settings()
    with pytest.raises(ValueError, match="attestation"):
        create_freeze(tmp_path, {}, split, settings, tmp_path / "no.json", reviewer="", attestation="")
    manifest = create_freeze(tmp_path, {}, split, settings, tmp_path / "freeze.json", reviewer="Human", attestation="gold-and-rules-reviewed")
    verify_freeze(tmp_path, {}, split, settings, manifest)
    (tmp_path / "prompts/workflow.md").write_text("changed after Test")
    with pytest.raises(ValueError, match="changed"):
        verify_freeze(tmp_path, {}, split, settings, manifest)


def test_source_directory_cannot_be_output(root):
    for path in ("data/replaced.xlsx", "..", "."):
        with pytest.raises(ValueError):
            safe_output(root, path)


def test_unimplemented_rules_are_not_silently_accepted(tmp_path, root):
    raw = yaml.safe_load((root / "config/rules.yaml").read_text(encoding="utf-8"))
    raw["answers"]["percent_decimal_places"] = 6
    (tmp_path / "config").mkdir()
    (tmp_path / "config/rules.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported research"):
        load_rules(tmp_path)


def test_selection_requires_reviewed_candidate_identity(tmp_path):
    from financial_annotation_harness.governance import validate_selection
    from financial_annotation_harness.io_utils import digest, write_new_json
    from test_ollama_provider import local_settings
    settings = local_settings()
    with pytest.raises(ValueError, match="undecided"):
        validate_selection(tmp_path, settings)
    summary = {"pending_reviews": 0, "models": [{"candidate_id": "m"}], "ollama_version": "0.fixture",
               "candidate_profiles": [{"candidate_id": "m", "model_tag": "fixture:tag", "digest": "digest1", "quantization": "Q4_K_M"}]}
    write_new_json(tmp_path / "summary.json", summary)
    selection = {"status": "SELECTED", "reviewer": "Researcher", "reason": "quality and speed", "candidate_id": "m",
        "evaluation_summary_path": "summary.json", "evaluation_summary_hash": digest(summary), "model_tag": "fixture:tag",
        "digest": "digest1", "quantization": "Q4_K_M", "ollama_version": "0.fixture"}
    write_new_json(tmp_path / "selection.json", selection)
    settings.selection_record = "selection.json"
    assert validate_selection(tmp_path, settings) == digest(selection)
    settings.model.generator_version = "different"
    with pytest.raises(ValueError, match="mismatch"):
        validate_selection(tmp_path, settings)


def test_local_config_does_not_change_code_freeze(root, tmp_path):
    from financial_annotation_harness.governance import project_hashes
    before = project_hashes(root)
    assert all(not p.endswith(".local.yaml") for p in before)
