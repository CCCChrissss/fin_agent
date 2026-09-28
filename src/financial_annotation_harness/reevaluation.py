"""Explicit, hash-pinned scoring revisions over immutable screening outputs."""
from .io_utils import digest


# Never permit generation, prompts, rules, data, or split drift through this path.
REVISION_FILES = {
    "src/financial_annotation_harness/validators.py",
    "src/financial_annotation_harness/evaluation.py",
    "src/financial_annotation_harness/screening_evaluation.py",
    "src/financial_annotation_harness/reevaluation.py",
    "src/financial_annotation_harness/cli.py",
}


def verify_revision(manifests: list[dict], current: dict, revision: dict) -> dict:
    required = {"schema_version", "revision_id", "reason", "authorization", "manifest_hashes",
                "source_manifest_hash", "split_hash", "changes"}
    if not isinstance(revision, dict) or set(revision) != required or revision["schema_version"] != "1.0":
        raise ValueError("Invalid evaluation revision schema")
    if any(not isinstance(revision[k], str) or not revision[k].strip() for k in ("revision_id", "reason", "authorization")):
        raise ValueError("Evaluation revision requires identity, reason, and authorization")
    if not manifests or revision["manifest_hashes"] != [digest(m) for m in manifests]:
        raise ValueError("Revision manifest hashes differ from immutable generation manifests")
    original = manifests[0]["project_hashes"]
    for manifest in manifests:
        if any(manifest[k] != revision[k] for k in ("source_manifest_hash", "split_hash")):
            raise ValueError("Revision source/split differs from generation")
        if manifest["project_hashes"] != original:
            raise ValueError("Revision cannot mix generation code versions")
    changes = {path: {"before": original.get(path), "after": current.get(path)}
               for path in sorted(set(original) | set(current)) if original.get(path) != current.get(path)}
    if not changes or revision["changes"] != changes:
        raise ValueError("Revision must declare every exact before/after code hash")
    if not set(changes) <= REVISION_FILES or any(v["after"] is None for v in changes.values()):
        raise ValueError("Only allowed scoring revision files may change; deletion is forbidden")
    return {"revision": revision, "revision_hash": digest(revision),
            "generation_project_hashes": original, "evaluation_project_hashes": current}
