"""Durable single-writer JSONL journals with explicit resume semantics."""

from __future__ import annotations

import os
from pathlib import Path

from .io_utils import canonical, digest, read_jsonl, timestamp


class TraceStore:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.lock_path = directory / ".writer.lock"
        self.lock = None

    def __enter__(self):
        self.lock = self.lock_path.open("x", encoding="utf-8")
        self.lock.write(str(os.getpid()))
        self.lock.flush()
        return self

    def __exit__(self, *args):
        if self.lock:
            self.lock.close()
            self.lock_path.unlink()

    def append(self, kind: str, record: dict) -> dict:
        if self.lock is None:
            raise RuntimeError("TraceStore must hold its single-writer lock")
        if kind not in ("events", "attempts", "finals"):
            raise ValueError(kind)
        row = {"trace_schema_version": "1.0", "timestamp": timestamp(), **record}
        row["record_hash"] = digest(row)
        with (self.directory / f"{kind}.jsonl").open("a", encoding="utf-8", newline="\n") as f:
            f.write(canonical(row) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return row

    def read(self, kind: str) -> list[dict]:
        rows = read_jsonl(self.directory / f"{kind}.jsonl")
        for row in rows:
            if row.get("record_hash") != digest({k: v for k, v in row.items() if k != "record_hash"}):
                raise ValueError("Trace integrity error")
        return rows

