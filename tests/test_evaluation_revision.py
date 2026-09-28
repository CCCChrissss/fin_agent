import copy

import pytest

from financial_annotation_harness.io_utils import digest


def fixture_revision():
    before = {"src/financial_annotation_harness/validators.py": "old", "prompts/contract.md": "prompt", "config/rules.yaml": "rules"}
    after = {**before, "src/financial_annotation_harness/validators.py": "new"}
    manifest = {"source_manifest_hash": "source", "split_hash": "split", "project_hashes": before}
    revision = {"schema_version": "1.0", "revision_id": "format-v1.1", "reason": "Accept equivalent rendering", "authorization": "Researcher approved format equivalence",
                "manifest_hashes": [digest(manifest)], "source_manifest_hash": "source", "split_hash": "split",
                "changes": {"src/financial_annotation_harness/validators.py": {"before": "old", "after": "new"}}}
    return manifest, after, revision


def test_revision_records_both_versions_without_mutating_manifest():
    from financial_annotation_harness.reevaluation import verify_revision
    manifest, current, revision = fixture_revision()
    original = copy.deepcopy(manifest)
    record = verify_revision([manifest], current, revision)
    assert manifest == original
    assert record["generation_project_hashes"] == manifest["project_hashes"]
    assert record["evaluation_project_hashes"] == current
    assert record["revision_hash"] == digest(revision)


@pytest.mark.parametrize("path", ["prompts/contract.md", "config/rules.yaml", "src/financial_annotation_harness/runner.py"])
def test_revision_cannot_authorize_generation_or_rule_drift(path):
    from financial_annotation_harness.reevaluation import verify_revision
    manifest, current, revision = fixture_revision()
    current[path] = "changed"
    revision["changes"][path] = {"before": manifest["project_hashes"].get(path), "after": "changed"}
    with pytest.raises(ValueError, match="allowed"):
        verify_revision([manifest], current, revision)


@pytest.mark.parametrize("mutation", ["after", "before", "manifest", "source", "split", "reason", "authorization", "extra"])
def test_revision_rejects_stale_or_incomplete_declaration(mutation):
    from financial_annotation_harness.reevaluation import verify_revision
    manifest, current, revision = fixture_revision()
    if mutation in ("before", "after"):
        revision["changes"]["src/financial_annotation_harness/validators.py"][mutation] = "stale"
    elif mutation == "manifest":
        revision["manifest_hashes"] = ["wrong"]
    elif mutation in ("source", "split"):
        revision[mutation + ("_manifest_hash" if mutation == "source" else "_hash")] = "wrong"
    elif mutation == "extra":
        current["src/financial_annotation_harness/cli.py"] = "unrecorded"
    else:
        revision[mutation] = ""
    with pytest.raises(ValueError):
        verify_revision([manifest], current, revision)


def test_cli_revision_is_explicit_and_screening_only():
    from financial_annotation_harness.cli import parser
    args = parser().parse_args(["evaluate-screening", "--experiment", "old", "--output", "new", "--revision", "revision.json"])
    assert str(args.revision) == "revision.json"
    with pytest.raises(SystemExit):
        parser().parse_args(["run", "--revision", "revision.json"])
