"""Independent semantic context; no Generator history or Gold reference."""

from __future__ import annotations

from .io_utils import canonical
from .schemas import JudgeResult


def judge_messages(question: str, artifact: dict, candidates: list[dict], selected: list[dict], rubric: str) -> list[dict]:
    return [
        {"role": "system", "content": rubric + "\nReturn a JSON object matching this schema:\n" + canonical(JudgeResult.model_json_schema())},
        {"role": "user", "content": canonical({"original_question": question, "generated_structured_artifact": artifact,
                                               "candidate_financial_facts": candidates, "selected_financial_facts": selected})},
    ]


def parse_judge(content: str | None) -> JudgeResult:
    return JudgeResult.model_validate_json(content or "")

