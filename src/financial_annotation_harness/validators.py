"""Computational checks. No Gold lookup and no semantic model calls."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from .facts import FactRepository, UNIT_MAP
from .python_executor import execute_python, inspect_python
from .schemas import Annotation, FailureCode, Issue, ValidationResult

VALIDATOR_NAMES = ("SchemaValidator", "FactExistenceValidator", "YearValidator", "UnitValidator",
                   "EvidenceValidator", "PythonSyntaxValidator", "PythonResultValidator", "QuestionTypeValidator")


def issue(code: str, rule: str, field: str, observed, expected: str, correction: str) -> Issue:
    return Issue(failure_code=FailureCode(code), rule_id=rule, field_path=field,
                 observed_value=observed, expected_constraint=expected, recommended_correction=correction)


def result(name: str, issues: list[Issue], **measurements) -> ValidationResult:
    version = ("1.4" if name == "QuestionTypeValidator" else
               "1.3" if name in {"PythonSyntaxValidator", "YearValidator", "EvidenceValidator"} else
               "1.2" if name in {"YearValidator", "EvidenceValidator"} else
               "1.1" if name == "UnitValidator" else "1.0")
    return ValidationResult(validator_name=name, validator_version=version, status="FAIL" if issues else "PASS", issues=issues, measurements=measurements)


def normalize_unit(unit: str) -> str:
    aliases = {"新台幣千元": "新臺幣仟元", "新臺幣千元": "新臺幣仟元", "新台幣仟元": "新臺幣仟元"}
    unit = aliases.get(unit, unit)
    return UNIT_MAP.get(unit, unit)


def canonical_year(value) -> int | None:
    """Normalize an ROC/Gregorian year scalar or display label to Gregorian int."""
    if type(value) is bool or value is None:
        return None
    if isinstance(value, str):
        match = re.fullmatch(r"\s*(\d{3,4})(?:\s*年)?\s*", value)
        if not match:
            return None
        value = match.group(1)
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or number != number.to_integral_value():
        return None
    year = int(number)
    return year + 1911 if 100 <= year < 200 else year


def answer_equal(actual, expected, unit: str) -> bool:
    if actual is None or expected is None:
        return False
    unit = normalize_unit(unit)
    if unit == "boolean":
        labels = {"yes": True, "no": False, "是": True, "否": False, "true": True, "false": False}
        def boolean(value):
            return value if type(value) is bool else labels.get(value.strip().lower()) if type(value) is str else None
        return boolean(actual) is not None and boolean(actual) == boolean(expected)
    if type(actual) is bool or type(expected) is bool:
        return False
    if unit == "year":
        a, b = canonical_year(actual), canonical_year(expected)
        return a is not None and b is not None and a == b
    try:
        a, b = Decimal(str(actual)), Decimal(str(expected))
        if not a.is_finite() or not b.is_finite():
            return False
        # Both generator and Gold must already supply their final rounded scalar.
        return a == b
    except (InvalidOperation, ValueError):
        return actual == expected


def question_years(question: str) -> set[int]:
    """Only explicit 3/4 digit years adjacent to year/range wording. No Gold input."""
    found = set()
    year_pattern = r"(?<!\d)(1\d{2}|20\d{2})(?=\s*(?:年|年度|至|到|與|和|to\b|and\b|[-–]))"
    for value in re.findall(year_pattern, question):
        year = int(value)
        found.add(year + 1911 if year < 200 else year)
    for value in re.findall(r"\b(20\d{2})\b", question):
        found.add(int(value))
    for start, end in re.findall(r"(1\d{2}|20\d{2})\s*(?:至|到|to|[-–])\s*(1\d{2}|20\d{2})", question):
        a, b = int(start), int(end)
        a = a + 1911 if a < 200 else a
        b = b + 1911 if b < 200 else b
        if 0 <= b - a <= 20:
            found.update(range(a, b + 1))
    return found


def context_facts(markdown: str) -> list[tuple[str, int, Decimal]]:
    """Parse the common simple Markdown table contract; never repair malformed cells."""
    rows = []
    years = []
    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells[0] in ("項目", "Concept", "Item"):
            # Newly supported borderless tables must have an actual delimiter row.
            # Preserve the existing bordered-table contract for old artifacts.
            if not line.strip().startswith("|"):
                separator = lines[index + 1] if index + 1 < len(lines) else ""
                delimiters = [c.strip() for c in separator.strip().strip("|").split("|")]
                if len(delimiters) != len(cells) or not all(re.fullmatch(r":?-+:?", c) for c in delimiters):
                    raise ValueError("Borderless context table requires a matching delimiter row")
            years = []
            for value in cells[1:]:
                match = re.fullmatch(r"(\d{3,4})(?:年)?", value)
                if not match:
                    raise ValueError("Context table headers must be ROC or Gregorian years")
                year = int(match[1])
                years.append(year + 1911 if year < 200 else year)
        elif re.fullmatch(r"[:\- ]+", cells[0]):
            continue
        else:
            if not years or len(cells) != len(years) + 1:
                raise ValueError("Context table width/header mismatch")
            for year, value in zip(years, cells[1:]):
                number = Decimal(value.replace(",", ""))
                if not number.is_finite():
                    raise ValueError("Non-finite context value")
                rows.append((cells[0], year, number))
    if not rows:
        raise ValueError("Golden Context requires at least one financial table")
    return rows


@dataclass
class ValidationContext:
    question_id: str
    question: str
    facts: FactRepository
    rules: dict
    retrieved_ids: set[str] = field(default_factory=set)
    execution: dict | None = None
    require_tool_provenance: bool = True
    input_parse_error: str | None = None


class SchemaValidator:
    def validate(self, raw, context):
        issues = []
        try:
            annotation = Annotation.model_validate(raw)
            if annotation.question_id != context.question_id:
                raise ValueError("question_id does not match input")
        except (ValidationError, ValueError, TypeError) as exc:
            observed = context.input_parse_error or str(exc)
            correction = ("Return one complete valid JSON object. Fix the reported line and column; escape quotes and newlines inside python_solution as JSON string content."
                          if context.input_parse_error else "Return one complete JSON annotation with the required types.")
            issues.append(issue("SCHEMA_ERROR", "SCHEMA-01", "$", observed, "Common annotation schema and input ID", correction))
        return result(type(self).__name__, issues)


class FactExistenceValidator:
    def validate(self, a, c):
        issues = []
        ids = a.retrieved_fact_ids + [e.fact_id for e in a.selected_evidence]
        for fid in sorted(set(ids)):
            if c.facts.get(fid) is None:
                issues.append(issue("EVIDENCE_ERROR", "FACT-01", "retrieved_fact_ids", fid, "Existing fact_id", "Retrieve an existing fact ID."))
            elif c.require_tool_provenance and fid not in c.retrieved_ids:
                issues.append(issue("EVIDENCE_ERROR", "FACT-02", "retrieved_fact_ids", fid, "Fact returned by this question's search calls", "Use the search tool before citing the fact."))
        return result(type(self).__name__, issues)


class YearValidator:
    def validate(self, a, c):
        issues = []
        times = {canonical_year(t.fiscal_year): t for t in a.semantic_parse.time}
        if len(times) != len(a.semantic_parse.time):
            issues.append(issue("YEAR_ERROR", "TIME-04", "semantic_parse.time", list(times), "One unambiguous period per year in v1", "Remove duplicate or contradictory time entries."))
        explicit = question_years(c.question)
        if explicit and set(times) != explicit:
            issues.append(issue("YEAR_ERROR", "TIME-01", "semantic_parse.time", sorted(times), f"Explicit question years: {sorted(explicit)}",
                f"Missing years: {sorted(explicit - set(times))}; extra years: {sorted(set(times) - explicit)}. Search financial facts for the requested years, then update semantic_parse.time, selected_evidence, retrieved_fact_ids, Context, Python and answer together. Do not only change the answer."))
        fact_years = set()
        for e in a.selected_evidence:
            f = c.facts.get(e.fact_id)
            if not f:
                continue
            year = f["fiscal_year"]
            fact_years.add(year)
            t = times.get(year)
            if t is None or (t.period_type, t.period_start, t.period_end) != (f["period_type"], f["period_start"], f["period_end"]):
                expected_period = {"fiscal_year": year, "period_type": f["period_type"],
                                   "period_start": f["period_start"], "period_end": f["period_end"]}
                issues.append(issue("YEAR_ERROR", "TIME-02", "semantic_parse.time", e.fact_id,
                                    f"Exact evidence period: {expected_period}",
                                    "Copy fiscal_year, period_type, period_start and period_end from the selected fact."))
        if not times or fact_years != set(times):
            issues.append(issue("YEAR_ERROR", "TIME-03", "selected_evidence", sorted(fact_years), "Evidence covers the declared years", "Retrieve evidence for each declared year."))
        return result(type(self).__name__, issues, explicit_years=sorted(explicit),
                      normalized_time_years=[canonical_year(t.fiscal_year) for t in a.semantic_parse.time])


class UnitValidator:
    def validate(self, a, c):
        issues = []
        units = set()
        for e in a.selected_evidence:
            f = c.facts.get(e.fact_id)
            if f:
                units.add(f["unit"])
                if normalize_unit(e.unit) != f["unit"]:
                    issues.append(issue("UNIT_ERROR", "UNIT-01", "selected_evidence.unit", e.unit, f["unit"], "Keep evidence values in the original source unit."))
        output = normalize_unit(a.unit)
        expected = {"Logic": "boolean", "Comparison": "year", "Ratio": "percent", "Growth_Rate": "percent"}.get(a.question_type)
        if expected and output != expected:
            issues.append(issue("UNIT_ERROR", "UNIT-02", "unit", a.unit, expected,
                                f"Set unit={expected!r} for question_type={a.question_type!r}."))
        if a.question_type in ("Single-Fact", "Arithmetic") and (len(units) != 1 or output not in units):
            issues.append(issue("UNIT_ERROR", "UNIT-03", "unit", a.unit, "Source monetary unit (v1 does not accept implicit rescaling)", "Return the numeric answer in its source unit."))
        if a.question_type in ("Ratio", "Growth_Rate", "Arithmetic") and len(units) > 1:
            issues.append(issue("UNIT_ERROR", "UNIT-04", "selected_evidence", sorted(units), "Dimensionally compatible operands", "Do not combine incompatible units."))
        source_labels = {f["unit"] for e in a.selected_evidence if (f := c.facts.get(e.fact_id))}
        stated_units = {normalize_unit(value.strip()) for value in re.findall(
            r"^[ \t]*(?:來源單位|單位|Source unit|Unit)[ \t]*[:：][ \t]*([^\r\n]+)",
            a.golden_context, flags=re.MULTILINE | re.IGNORECASE)}
        if source_labels and stated_units != source_labels:
            issues.append(issue("UNIT_ERROR", "UNIT-05", "golden_context", sorted(stated_units), "Context states the units of its source values", "Label the source table units explicitly and resolve conflicting units."))
        return result(type(self).__name__, issues)


class EvidenceValidator:
    def validate(self, a, c):
        issues = []
        selected = [e.fact_id for e in a.selected_evidence]
        if not selected or len(selected) != len(set(selected)) or set(selected) != set(a.retrieved_fact_ids) or len(a.retrieved_fact_ids) != len(set(a.retrieved_fact_ids)):
            from collections import Counter
            retrieved_counts, selected_counts = Counter(a.retrieved_fact_ids), Counter(selected)
            differences = {
                "retrieved_fact_ids": list(a.retrieved_fact_ids),
                "selected_evidence_fact_ids": selected,
                "only_in_retrieved_fact_ids": sorted(set(a.retrieved_fact_ids) - set(selected)),
                "only_in_selected_evidence": sorted(set(selected) - set(a.retrieved_fact_ids)),
                "duplicate_retrieved_fact_ids": sorted(k for k, n in retrieved_counts.items() if n > 1),
                "duplicate_selected_evidence_fact_ids": sorted(k for k, n in selected_counts.items() if n > 1),
            }
            correction = (
                f"IDs only in retrieved_fact_ids: {differences['only_in_retrieved_fact_ids']}; "
                f"IDs only in selected_evidence: {differences['only_in_selected_evidence']}. "
                f"Duplicate retrieved IDs: {differences['duplicate_retrieved_fact_ids']}; "
                f"duplicate selected IDs: {differences['duplicate_selected_evidence_fact_ids']}. "
                "Check the original question and choose only the required evidence. "
                "Set retrieved_fact_ids to exactly those selected_evidence fact IDs, each once; "
                "do not include unselected search candidates. Keep the selection nonempty. "
                "If the selection changes, update Context, Python bindings and answer consistently.")
            issues.append(issue("EVIDENCE_ERROR", "EVID-01", "retrieved_fact_ids/selected_evidence", differences,
                                "Nonempty unique selected evidence matching retrieved_fact_ids", correction))
        expected_rows = []
        binding_targets = set()
        for e in a.selected_evidence:
            f = c.facts.get(e.fact_id)
            if not f:
                continue
            if f["value_decimal"] is None:
                issues.append(issue("EVIDENCE_ERROR", "NULL-01", "selected_evidence", e.fact_id, "Reported value, never not_reported as zero", "Do not use an unreported value as a numeric operand."))
                continue
            if Decimal(e.value) != Decimal(f["value_decimal"]):
                issues.append(issue("EVIDENCE_ERROR", "EVID-02", "selected_evidence.value", e.value, f["value_decimal"], "Copy the exact value of the referenced fact."))
            expected_rows.append((f["concept_zh"], f["fiscal_year"], Decimal(f["value_decimal"])))
            target = (e.variable_name, e.index_key)
            if target in binding_targets:
                issues.append(issue("EVIDENCE_ERROR", "EVID-03", "selected_evidence", str(target), "Unique variable/index binding", "Bind each fact unambiguously."))
            binding_targets.add(target)
            if c.execution and c.execution["success"]:
                value = c.execution["locals"].get(e.variable_name)
                if e.index_key is not None:
                    value = value.get(str(e.index_key), value.get(e.index_key)) if isinstance(value, dict) else None
                if value is None or not answer_equal(value, e.value, f["unit"]):
                    correction = (f"Use index_key=null because {e.variable_name} is a scalar, or make "
                                  f"{e.variable_name} a dictionary containing key {e.index_key}.") if e.index_key is not None and not isinstance(c.execution["locals"].get(e.variable_name), dict) else "Assign the referenced source value to the declared semantic variable/index."
                    issues.append(issue("EVIDENCE_ERROR", "POT-01", "python_solution", e.variable_name,
                                        f"Binding {e.variable_name}[{e.index_key!r}] equals evidence value {e.value}" if e.index_key is not None else f"Variable {e.variable_name} equals evidence value {e.value}",
                                        correction))
        try:
            actual_rows = context_facts(a.golden_context)
            if sorted(actual_rows) != sorted(expected_rows):
                from collections import Counter
                missing = list((Counter(expected_rows) - Counter(actual_rows)).elements())
                extra = list((Counter(actual_rows) - Counter(expected_rows)).elements())
                raise ValueError(f"Context rows differ from selected evidence. Missing source rows: {missing!r}; unexpected rows: {extra!r}. Copy exact source concept labels, years and values; do not abbreviate labels.")
        except (ValueError, InvalidOperation) as exc:
            issues.append(issue("EVIDENCE_ERROR", "GOLD-01", "golden_context", str(exc), "Only the selected concept/year/value rows", "Write a Markdown financial table containing exactly the selected evidence."))
        # Trace required operands to the returned expression, not merely unused assignments.
        try:
            tree = inspect_python(a.python_solution)
            assignments = {n.targets[0].id: n.value for n in tree.body[0].body if isinstance(n, ast.Assign)}
            pending = [n.id for n in ast.walk(tree.body[0].body[-1].value) if isinstance(n, ast.Name)]
            used = set()
            while pending:
                name = pending.pop()
                if name in used:
                    continue
                used.add(name)
                if name in assignments:
                    pending.extend(n.id for n in ast.walk(assignments[name]) if isinstance(n, ast.Name))
            for e in a.selected_evidence:
                if e.variable_name not in used:
                    issues.append(issue("EVIDENCE_ERROR", "POT-GROUND", "python_solution", e.variable_name, "Evidence grounding participates in the returned computation", "Use the source operands in the reasoning instead of returning a hard-coded answer."))
            allowed_constants = {Decimal(x) for x in (0, 1, 2, 100, len(a.selected_evidence))}
            allowed_constants.update(Decimal(t.fiscal_year) for t in a.semantic_parse.time)
            for number in re.findall(r"(?<!\d)\d+(?:\.\d+)?", c.question):
                allowed_constants.update((Decimal(number), Decimal(number) / 100))
            grounded_nodes = set()
            for e in a.selected_evidence:
                assigned = assignments.get(e.variable_name)
                if isinstance(assigned, (ast.Constant, ast.UnaryOp, ast.Dict, ast.List, ast.Tuple)):
                    grounded_nodes.update(id(n) for n in ast.walk(assigned))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and type(node.value) in (int, float) and id(node) not in grounded_nodes and Decimal(str(node.value)) not in allowed_constants:
                    issues.append(issue("EVIDENCE_ERROR", "POT-01", "python_solution", node.value, "Financial literals require evidence grounding; other constants require a mathematical/question role", "Bind financial values to selected evidence and name question thresholds."))
        except (ValueError, SyntaxError, RecursionError):
            pass  # PythonSyntaxValidator reports the actual parsing/execution error.
        return result(type(self).__name__, issues, scope="internal consistency; no Gold evidence lookup")


class PythonSyntaxValidator:
    def validate(self, a, c):
        c.execution = execute_python(a.python_solution, **c.rules["execution"])
        issues = []
        if not c.execution["success"]:
            correction = "Correct the program within the common restricted Python contract."
            if a.question_type == "Comparison":
                correction = (
                    "Replace the failing program with assignments and one final return. Replace statement if/elif/else. "
                    "Keep every selected_evidence variable_name as an assigned source variable, then build a "
                    "Gregorian-year keyed dictionary from those variables, such as "
                    "values_by_year = {2024: value_2024, 2025: value_2025}. "
                    "For the highest value use return max(values_by_year, key=values_by_year.get); use min for the "
                    "lowest; return the numeric max/min year variable directly; do not call str() and do not convert "
                    "it to an ROC year. Never add if/elif/else, join(), str(), or lambda. "
                    "Do not copy financial literals directly into a differently named dictionary.")
            issues.append(issue("PYTHON_EXECUTION_ERROR", "POT-EXEC", "python_solution", c.execution["error"], "Safe supported solution() returning a scalar", correction))
        return result(type(self).__name__, issues, execution=c.execution)


class PythonResultValidator:
    def validate(self, a, c):
        if not c.execution or not c.execution["success"]:
            return ValidationResult(validator_name=type(self).__name__, status="SKIPPED", measurements={"reason": "execution failed"})
        issues = []
        if not answer_equal(c.execution["result"], a.answer, a.unit):
            observed = {"annotation_answer": a.answer, "python_result": c.execution["result"]}
            issues.append(issue("PYTHON_ANSWER_MISMATCH", "POT-02", "answer", observed,
                                "answer exactly equals the executed solution() result after the declared unit normalization",
                                f"Set answer to {c.execution['result']!r}, or correct solution() if that result is wrong."))
        return result(type(self).__name__, issues)


def _expanded(node, assignments: dict[str, ast.AST], depth=0):
    if depth > 30:
        return node
    if isinstance(node, ast.Name) and node.id in assignments:
        return _expanded(assignments[node.id], assignments, depth + 1)
    return node


class QuestionTypeValidator:
    def validate(self, a, c):
        issues = []
        measurements = {}
        try:
            tree = inspect_python(a.python_solution)
        except (ValueError, SyntaxError, RecursionError):
            return ValidationResult(validator_name=type(self).__name__, status="SKIPPED")
        fn = tree.body[0]
        assignments = {n.targets[0].id: n.value for n in fn.body if isinstance(n, ast.Assign)}
        ret = _expanded(fn.body[-1].value, assignments)
        nodes = list(ast.walk(tree))
        calls = {n.func.id for n in nodes if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        divisions = [n for n in nodes if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div)]
        subtracts = [n for n in nodes if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Sub)]
        kind = a.question_type
        valid = True
        if kind == "Single-Fact":
            valid = len(a.selected_evidence) == 1 and not any(isinstance(n, (ast.BinOp, ast.Compare, ast.IfExp)) for n in nodes) and not calls
        elif kind == "Comparison":
            valid = len(a.selected_evidence) >= 2 and bool(calls & {"min", "max", "sorted"}) and not isinstance(ret, ast.IfExp)
            years = {t.fiscal_year for t in a.semantic_parse.time}
            year_example = max(years) if years else 2025
            comparison_correction = (
                f"Return a numeric Gregorian year in both fields; for example answer={year_example}, not an ROC/display label. "
                "In solution(), bind evidence values in a Gregorian-year keyed values_by_year dictionary and use "
                "return max(values_by_year, key=values_by_year.get) for the highest value or min(...) for the lowest value.")
            outputs = {"answer": a.answer}
            if c.execution and c.execution["success"]:
                outputs["python_solution"] = c.execution["result"]
            normalized_outputs = {field_name: canonical_year(value) for field_name, value in outputs.items()}
            measurements["normalized_year_outputs"] = normalized_outputs
            for field_name, value in outputs.items():
                if normalized_outputs[field_name] not in years:
                    issues.append(issue("QUESTION_TYPE_ERROR", "TYPE-03", field_name, value,
                        f"Comparison returns a numeric Gregorian year from declared years {sorted(years)}",
                        comparison_correction))
        elif kind == "Logic":
            valid = any(isinstance(n, ast.Compare) for n in nodes) and (isinstance(ret, (ast.IfExp, ast.Compare, ast.BoolOp)) or bool(calls & {"all", "any"}))
        elif kind == "Growth_Rate":
            valid = bool(divisions and subtracts) and len(a.selected_evidence) >= 2 and not isinstance(ret, (ast.IfExp, ast.Compare, ast.BoolOp))
        elif kind == "Ratio":
            valid = bool(divisions) and not subtracts and len(a.selected_evidence) >= 2 and not isinstance(ret, (ast.IfExp, ast.Compare, ast.BoolOp))
        elif kind == "Arithmetic":
            valid = bool(calls & {"sum"}) or any(isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)) for n in nodes)
            valid = valid and not isinstance(ret, (ast.IfExp, ast.Compare, ast.BoolOp))
        if not valid:
            correction = (comparison_correction if kind == "Comparison" else
                          "Check the final operation, not just an intermediate operator.")
            issues.append(issue("QUESTION_TYPE_ERROR", "TYPE-01", "question_type", kind, "Primary program operation matches declared question type", correction))
        # For two-operand ratio/growth, compute from declared facts, never Gold answers.
        fs = [c.facts.get(e.fact_id) for e in a.selected_evidence]
        if kind in ("Ratio", "Growth_Rate") and len(fs) == 2 and all(f and f["value_decimal"] is not None for f in fs) and c.execution and c.execution["success"]:
            if kind == "Growth_Rate":
                old, new = sorted(fs, key=lambda f: f["fiscal_year"])
                formula_valid = old["fiscal_year"] < new["fiscal_year"] and old["concept_id"] == new["concept_id"]
                numerator = float(new["value_decimal"]) - float(old["value_decimal"])
                denominator = float(old["value_decimal"])
            else:
                numerator, denominator = (float(f["value_decimal"]) for f in fs)
                formula_valid = fs[0]["fiscal_year"] == fs[1]["fiscal_year"] and fs[0]["concept_id"] != fs[1]["concept_id"]
            if denominator == 0 or not formula_valid or not answer_equal(c.execution["result"], round(numerator / denominator * 100, 2) if denominator else None, "percent"):
                issues.append(issue("FORMULA_ERROR", "TYPE-02", "python_solution", c.execution["result"], "Growth: (new-old)/old*100; Ratio: first selected operand / second *100; round(...,2)", "Use correctly ordered operands, a nonzero denominator, and percentage formatting."))
        return result(type(self).__name__, issues, **measurements)


def validate_all(raw, context: ValidationContext) -> tuple[Annotation | None, list[ValidationResult]]:
    schema = SchemaValidator().validate(raw, context)
    if schema.status != "PASS":
        return None, [schema] + [ValidationResult(validator_name=n, status="SKIPPED") for n in VALIDATOR_NAMES[1:]]
    a = Annotation.model_validate(raw)
    # Execution precedes grounding validation, but all results retain canonical order.
    execution = PythonSyntaxValidator().validate(a, context)
    values = [schema, FactExistenceValidator().validate(a, context), YearValidator().validate(a, context),
              UnitValidator().validate(a, context), EvidenceValidator().validate(a, context), execution,
              PythonResultValidator().validate(a, context), QuestionTypeValidator().validate(a, context)]
    return a, values


def all_pass(results: list[ValidationResult]) -> bool:
    return len(results) == len(VALIDATOR_NAMES) and {r.validator_name for r in results} == set(VALIDATOR_NAMES) and all(r.status == "PASS" for r in results)
