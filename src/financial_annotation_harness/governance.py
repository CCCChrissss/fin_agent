"""Explicit freeze attestation and immutable experiment snapshots."""

from __future__ import annotations

import platform
import sys
from importlib.metadata import distributions
from pathlib import Path

from .io_utils import digest, file_hash, read_json, timestamp, write_new_json
from .schemas import Annotation


def project_hashes(root: Path) -> dict[str, str]:
    paths = [root / "pyproject.toml", root / "requirements.lock", root / "docs/experiment_protocol.md",
             root / "docs/research_context.md", root / "docs/evaluation_rubric.md", root / "docs/implementation_design.md"]
    for folder, pattern in (("src", "*.py"), ("prompts", "*.md"), ("config", "*.yaml")):
        paths.extend(p for p in (root / folder).rglob(pattern) if not p.name.endswith(".local.yaml"))
    supplement = root / "docs/local_model_screening.md"
    if supplement.exists():
        paths.append(supplement)
    amendment = root / "docs/ai_review_amendment.md"
    if amendment.exists():
        paths.append(amendment)
    return {p.relative_to(root).as_posix(): file_hash(p) for p in sorted(set(paths))}


def review_provenance(root, settings, source_manifest):
    if settings.review_mode == "human":
        return {"review_mode": "human"}
    if not settings.review_record:
        raise ValueError("AI review requires an explicit review record")
    path = (root / settings.review_record).resolve(strict=True)
    if not path.is_relative_to(root):
        raise ValueError("AI review record must be inside project")
    record = read_json(path)
    if record.get("source_sha256") != source_manifest["sha256"]:
        raise ValueError("AI review source mismatch")
    if (record.get("review_kind") != "ai_assisted" or record.get("status") != "COMPLETE"
            or not record.get("reviewer") or record.get("question_count") != 60
            or record.get("reviewed_question_count") != 60
            or record.get("rules_reviewed") is not True or record.get("judge_rubric_reviewed") is not True):
        raise ValueError("Incomplete AI review record")
    return {"review_mode": "ai_assisted", "review_record_hash": file_hash(path),
            "reviewer": record["reviewer"], "human_review_completed": False}


def validate_selection(root, settings):
    if settings.model.provider != "ollama":
        return None
    if not settings.selection_record:
        raise ValueError("Formal Generator is undecided; a human selection record is required")
    path = (root / settings.selection_record).resolve(strict=True)
    if not path.is_relative_to(root):
        raise ValueError("Selection record must be in project")
    selection = read_json(path)
    if selection.get("status") != "SELECTED" or not selection.get("reviewer", "").strip() or not selection.get("reason", "").strip():
        raise ValueError("Human model selection is incomplete")
    for key, value in {"model_tag": settings.model.generator_model, "digest": settings.model.generator_version,
                       "quantization": settings.model.expected_quantization, "ollama_version": settings.model.expected_ollama_version}.items():
        if selection.get(key) != value:
            raise ValueError(f"Selection/model mismatch: {key}")
    evidence_path = (root / selection.get("evaluation_summary_path", "")).resolve(strict=True)
    if not evidence_path.is_relative_to(root) or not evidence_path.is_file():
        raise ValueError("Selection requires its screening evaluation summary")
    evidence = read_json(evidence_path)
    if digest(evidence) != selection.get("evaluation_summary_hash") or evidence.get("pending_reviews") != 0:
        raise ValueError("Selection evidence changed or independent reviews are pending")
    if selection.get("candidate_id") not in {r["candidate_id"] for r in evidence["models"]}:
        raise ValueError("Selected candidate absent from screening")
    profile = next(r for r in evidence["candidate_profiles"] if r["candidate_id"] == selection["candidate_id"])
    if any(selection.get(k) != profile[k] for k in ("model_tag", "digest", "quantization")) or selection["ollama_version"] != evidence["ollama_version"]:
        raise ValueError("Selected profile differs from evaluated candidate")
    return digest(selection)


def create_freeze(root: Path, source_manifest: dict, split: dict, settings, output: Path, *, reviewer: str, attestation: str):
    expected_attestation = "ai-reviewed-gold-and-rules" if settings.review_mode == "ai_assisted" else "gold-and-rules-reviewed"
    if not reviewer.strip() or attestation != expected_attestation:
        raise ValueError("Human review attestation required; software cannot approve Gold")
    review = review_provenance(root, settings, source_manifest)
    if len(split["development"]) != 12 or len(split["test"]) != 48 or set(split["development"]) & set(split["test"]):
        raise ValueError("Invalid main experiment split")
    settings.require_live()
    selection_hash = validate_selection(root, settings)
    manifest = {"schema_version": "1.0", "reviewer": reviewer, "attestation": attestation, "frozen_at": timestamp(),
                "source_manifest_hash": digest(source_manifest), "split_hash": digest(split),
                "settings_hash": digest(settings.model_dump()), "annotation_schema_hash": digest(Annotation.model_json_schema()),
                "project_hashes": project_hashes(root), "selection_hash": selection_hash, "review_provenance": review}
    if settings.model.provider == "ollama":
        from .model_client import create_provider
        from .runtime_environment import environment_snapshot
        provider = create_provider(settings, allow_live=True)
        try:
            manifest["runtime"] = provider.runtime
            manifest["hardware"] = environment_snapshot()
        finally:
            provider.close()
    write_new_json(output, manifest)
    return manifest


def verify_freeze(root: Path, source_manifest: dict, split: dict, settings, freeze: dict):
    checks = {"source_manifest_hash": digest(source_manifest), "split_hash": digest(split),
              "settings_hash": digest(settings.model_dump()), "annotation_schema_hash": digest(Annotation.model_json_schema()),
              "project_hashes": project_hashes(root)}
    checks["selection_hash"] = validate_selection(root, settings)
    expected_attestation = "ai-reviewed-gold-and-rules" if settings.review_mode == "ai_assisted" else "gold-and-rules-reviewed"
    if settings.review_mode == "ai_assisted":
        checks["review_provenance"] = review_provenance(root, settings, source_manifest)
    if freeze.get("attestation") != expected_attestation or not freeze.get("reviewer"):
        raise ValueError("Missing human freeze attestation")
    for name, value in checks.items():
        if freeze.get(name) != value:
            raise ValueError(f"Frozen experiment changed: {name}; create a separate regression study")


def environment_manifest() -> dict:
    return {"python": sys.version, "platform": platform.platform(),
            "packages": {d.metadata["Name"]: d.version for d in distributions()}}
