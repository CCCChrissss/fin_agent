"""Deterministic data access. This module never loads question or Gold files."""

from __future__ import annotations

import json
import sqlite3
import unicodedata
from pathlib import Path

from .io_utils import canonical
from .schemas import SearchRequest

UNIT_MAP = {"新臺幣仟元": "TWD_thousand", "元": "TWD", "股": "share", "%": "percent", "年": "year", "Yes/No": "boolean"}
STATEMENT_MAP = {"簡明綜合損益表": "income_statement", "簡明資產負債表": "balance_sheet"}


def create_database(path: Path, facts: list[dict], source: dict) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript("""
            CREATE TABLE dataset_sources (source_id TEXT PRIMARY KEY, manifest_json TEXT NOT NULL);
            CREATE TABLE financial_facts (
                fact_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES dataset_sources(source_id),
                company TEXT NOT NULL, stock_code TEXT NOT NULL,
                fiscal_year INTEGER NOT NULL, roc_year INTEGER NOT NULL,
                statement TEXT NOT NULL CHECK(statement IN ('income_statement','balance_sheet')),
                statement_raw TEXT NOT NULL, concept_id TEXT NOT NULL, concept_zh TEXT NOT NULL,
                value_decimal TEXT, value_status TEXT NOT NULL,
                unit TEXT NOT NULL, unit_raw TEXT NOT NULL,
                period_type TEXT NOT NULL CHECK(period_type IN ('instant','duration')),
                period_start TEXT, period_end TEXT NOT NULL,
                source_description TEXT NOT NULL, source_sheet TEXT NOT NULL,
                source_row INTEGER NOT NULL, source_value_cell TEXT NOT NULL,
                CHECK(fiscal_year=roc_year+1911),
                CHECK((value_status='not_reported' AND value_decimal IS NULL) OR
                      (value_status='reported_zero' AND CAST(value_decimal AS REAL)=0 AND value_decimal IS NOT NULL) OR
                      (value_status='reported' AND value_decimal IS NOT NULL AND CAST(value_decimal AS REAL)<>0)),
                UNIQUE(stock_code, concept_id, fiscal_year, statement, period_type)
            );
            CREATE INDEX facts_lookup ON financial_facts(concept_id, fiscal_year, statement);
        """)
        conn.execute("INSERT INTO dataset_sources VALUES (?,?)", (source["sha256"], canonical(source)))
        for fact in facts:
            keys = list(fact)
            conn.execute(f"INSERT INTO financial_facts ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})", list(fact.values()))


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).lower().replace("_", " ").split())


def tool_fact(row: dict) -> dict:
    return {"fact_id": row["fact_id"], "concept_id": row["concept_id"], "concept": row["concept_zh"],
            "year": row["fiscal_year"], "roc_year": row["roc_year"], "value": row["value_decimal"],
            "value_status": row["value_status"], "unit": row["unit"], "statement": row["statement"],
            "period_type": row["period_type"], "period_start": row["period_start"], "period_end": row["period_end"],
            "provenance": {"sheet": row["source_sheet"], "row": row["source_row"], "value_cell": row["source_value_cell"]}}


class FactRepository:
    def __init__(self, path: Path, aliases: dict[str, list[str]] | None = None, top_k: int = 12):
        self.path = path.resolve(strict=True)
        self.aliases = aliases or {}
        self.top_k = top_k
        with self.connect() as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables != {"financial_facts", "dataset_sources"}:
                raise ValueError("Facts DB must not contain question/Gold tables")

    def connect(self):
        conn = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        return conn

    def all(self) -> list[dict]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM financial_facts ORDER BY fact_id")]

    def get(self, fact_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM financial_facts WHERE fact_id=?", (fact_id,)).fetchone()
            return dict(row) if row else None

    def search_financial_facts(self, query: str, years=None, statement_type=None, top_k=None) -> dict:
        request = SearchRequest(query=query, years=years, statement_type=statement_type, top_k=top_k)
        query_norm = normalize(request.query)
        ranked = []
        for fact in self.all():
            if years is not None and fact["fiscal_year"] not in years:
                continue
            if statement_type and fact["statement"] != statement_type:
                continue
            names = [fact["concept_id"], fact["concept_zh"], *self.aliases.get(fact["concept_id"], [])]
            names = [normalize(name) for name in names]
            score = max((3 if query_norm == n else 2 if query_norm in n else
                         1 if set(query_norm.split()) <= set(n.split()) else 0) for n in names)
            if score:
                ranked.append((-score, fact["fact_id"], fact))
        ranked.sort(key=lambda x: (x[0], x[1]))
        limit = request.top_k or self.top_k
        candidates = [tool_fact(row) for _, _, row in ranked[:limit]]
        missing = [{"kind": "not_reported", "fact_id": x["fact_id"]} for x in candidates if x["value"] is None]
        if not ranked:
            missing.append({"kind": "no_match", "query": query})
        return {"success": True, "query": query,
                "applied_filters": {"years": years, "statement_type": statement_type, "top_k": limit},
                "candidates": candidates, "total_matches": len(ranked), "truncated": len(ranked) > limit,
                "missing_information": missing,
                "retry_suggestion": "Refine the concept or filters; no-match does not prove out-of-scope." if not ranked else None,
                "recommended_next_action": "refine_query" if not ranked else "select_evidence", "error": None}

