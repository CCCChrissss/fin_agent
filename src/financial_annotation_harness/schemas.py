"""Shared contracts. All four conditions receive the same annotation schema."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

QUESTION_TYPES = ("Single-Fact", "Comparison", "Growth_Rate", "Ratio", "Logic", "Arithmetic")
QuestionType = Literal["Single-Fact", "Comparison", "Growth_Rate", "Ratio", "Logic", "Arithmetic"]
Statement = Literal["income_statement", "balance_sheet"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class FailureCode(StrEnum):
    SCHEMA_ERROR = "SCHEMA_ERROR"
    SEMANTIC_PARSE_ERROR = "SEMANTIC_PARSE_ERROR"
    CONCEPT_ERROR = "CONCEPT_ERROR"
    EVIDENCE_ERROR = "EVIDENCE_ERROR"
    YEAR_ERROR = "YEAR_ERROR"
    UNIT_ERROR = "UNIT_ERROR"
    QUESTION_TYPE_ERROR = "QUESTION_TYPE_ERROR"
    FORMULA_ERROR = "FORMULA_ERROR"
    PYTHON_EXECUTION_ERROR = "PYTHON_EXECUTION_ERROR"
    PYTHON_ANSWER_MISMATCH = "PYTHON_ANSWER_MISMATCH"
    UNSUPPORTED_ANSWER = "UNSUPPORTED_ANSWER"
    OTHER = "OTHER"


class TimeRequirement(StrictModel):
    fiscal_year: int
    period_type: Literal["instant", "duration"]
    period_start: str | None
    period_end: str


class SemanticParse(StrictModel):
    time: list[TimeRequirement]
    concept: list[str]
    filter: list[str]
    logic: str


class EvidenceBinding(StrictModel):
    fact_id: str
    value: str = Field(pattern=r"^-?\d+(?:\.\d+)?$")
    unit: str
    variable_name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    index_key: int | str | None


class Annotation(StrictModel):
    question_id: str
    semantic_parse: SemanticParse
    question_type: QuestionType
    retrieved_fact_ids: list[str]
    selected_evidence: list[EvidenceBinding]
    golden_context: str
    python_solution: str
    answer: int | float | str | bool | None
    unit: str


class QuestionInput(StrictModel):
    """Only this object, not GoldRecord/metadata, may enter the online runner."""

    question_id: str
    question: str
    language: Literal["zh", "en"]


class SearchRequest(StrictModel):
    query: str = Field(min_length=1, max_length=500)
    years: list[int] | None = None
    statement_type: Statement | None = None
    top_k: int | None = Field(default=None, ge=1, le=138)


class Issue(StrictModel):
    failure_code: FailureCode
    rule_id: str
    field_path: str
    observed_value: object
    expected_constraint: str
    recommended_correction: str


class ValidationResult(StrictModel):
    validator_name: str
    validator_version: str = "1.0"
    status: Literal["PASS", "FAIL", "SKIPPED", "ERROR"]
    issues: list[Issue] = Field(default_factory=list)
    measurements: dict = Field(default_factory=dict)


class JudgeResult(StrictModel):
    semantic_parse_pass: bool
    concept_pass: bool
    evidence_pass: bool
    golden_context_pass: bool
    overall_pass: bool
    failure_codes: list[FailureCode]
    issues: list[Issue]
    feedback: str

    @model_validator(mode="after")
    def consistent(self):
        expected = all((self.semantic_parse_pass, self.concept_pass,
                        self.evidence_pass, self.golden_context_pass))
        if self.overall_pass != expected:
            raise ValueError("overall_pass must equal the AND of four criteria")
        allowed = {FailureCode.SEMANTIC_PARSE_ERROR, FailureCode.CONCEPT_ERROR,
                   FailureCode.EVIDENCE_ERROR, FailureCode.UNSUPPORTED_ANSWER}
        if any(code not in allowed for code in self.failure_codes):
            raise ValueError("Judge must not report deterministic failures")
        if set(self.failure_codes) != {x.failure_code for x in self.issues}:
            raise ValueError("failure_codes and issues must agree")
        if self.overall_pass and (self.failure_codes or self.issues):
            raise ValueError("PASS cannot include failures")
        if not self.overall_pass and not self.issues:
            raise ValueError("FAIL requires structured feedback")
        return self

