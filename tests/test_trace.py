import json

import pytest

from financial_annotation_harness.trace import TraceStore


def test_single_writer_and_tamper_detection(tmp_path):
    with TraceStore(tmp_path / "traces") as first:
        with pytest.raises(FileExistsError):
            with TraceStore(tmp_path / "traces"):
                pass
        first.append("events", {"event": "test", "value": 42})
    assert not (tmp_path / "traces/.writer.lock").exists()
    path = tmp_path / "traces/events.jsonl"
    value = json.loads(path.read_text())
    value["value"] = 43
    path.write_text(json.dumps(value) + "\n")
    with pytest.raises(ValueError, match="integrity"):
        TraceStore(tmp_path / "traces").read("events")


def test_append_requires_context_manager(tmp_path):
    with pytest.raises(RuntimeError):
        TraceStore(tmp_path).append("events", {})

