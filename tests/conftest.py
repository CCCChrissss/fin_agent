import socket
import uuid
from pathlib import Path

import pytest

from financial_annotation_harness.cli import load_prompts
from financial_annotation_harness.config import load_rules
from financial_annotation_harness.demo import demo_data
from financial_annotation_harness.facts import FactRepository, create_database


def pytest_configure(config):
    if config.option.basetemp is None:
        # A new path per invocation avoids deleting/reusing another user's temp tree.
        config.option.basetemp = str(Path(__file__).resolve().parents[1] / "artifacts/runtime" / f"pytest-{uuid.uuid4().hex}")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Real network access is forbidden in offline tests")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture
def root():
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def specimen(tmp_path):
    source, facts, question, artifact, gold = demo_data()
    path = tmp_path / "facts.sqlite"
    create_database(path, facts, source)
    return FactRepository(path), question, artifact, gold


@pytest.fixture
def rules(root):
    return load_rules(root)


@pytest.fixture
def prompts(root):
    return load_prompts(root)
