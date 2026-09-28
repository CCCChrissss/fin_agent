"""One runner, four immutable condition definitions, external attempt state."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict

from .config import Settings
from .facts import FactRepository, tool_fact
from .io_utils import canonical, digest
from .judge import judge_messages, parse_judge
from .schemas import Annotation, QuestionInput, SearchRequest
from .trace import TraceStore
from .validators import ValidationContext, all_pass, canonical_year, normalize_unit, question_years, validate_all


def parse_artifact_json(raw):
    try:
        return json.loads(raw), None
    except json.JSONDecodeError as exc:
        return None, f"JSONDecodeError at line {exc.lineno} column {exc.colno}: {exc.msg}"
    except TypeError as exc:
        return None, f"TypeError: {exc}"


def search_tool_schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "search_financial_facts",
            "description": (
                "Deterministic financial fact lookup. "
                "Returns source financial facts, never the final answer. "
                "IMPORTANT: query must contain ONLY the accounting concept, "
                "for example '營業收入'. "
                "Do NOT include fiscal years such as '2025', '114年', or other "
                "time expressions in query. "
                "Fiscal years must be supplied through the years parameter. "
                "When candidates matching the required concept and years have "
                "already been returned, select the required evidence and stop "
                "searching unless information is genuinely missing. "
                "No match alone does not prove out-of-scope."
            ),
            "parameters": SearchRequest.model_json_schema(),
        },
    }


def completion_gate(validation_results, judge_result) -> bool:
    return all_pass(validation_results) and judge_result is not None and judge_result.overall_pass


def sum_usage(turns, field):
    values = [getattr(t, field) for t in turns]
    return sum(values) if values and all(v is not None for v in values) else None


def finalization_ready(question: str, retrieved: dict) -> bool:
    if not retrieved or any(f.get("value_status") != "reported" for f in retrieved.values()):
        return False
    required = question_years(question)
    available = {f.get("year", f.get("fiscal_year")) for f in retrieved.values()}
    return not required or required <= available


class AnnotationRunner:
    def __init__(self, settings: Settings, facts: FactRepository, rules: dict, prompts: dict[str, str], client, traces: TraceStore,
                 *, trace_context: dict | None = None):
        self.settings, self.facts, self.rules = settings, facts, rules
        self.prompts, self.client, self.traces = prompts, client, traces
        self.trace_context = trace_context or {"experiment_kind": "main"}

    def run_question(self, question: QuestionInput, *, source_question_id: str, condition: str, run_index: int,
                     experiment_id: str) -> dict:
        if condition not in "ABCD" or len(condition) != 1 or run_index not in (1, 2, 3):
            raise ValueError("Invalid protocol condition/run")
        identity = {**self.trace_context, "run_id": f"{experiment_id}/run_{run_index:02d}/{condition}",
                    "question_id": source_question_id, "public_question_id": question.question_id,
                    "condition": condition, "run_index": run_index}
        existing = [r for r in self.traces.read("finals") if r["question_id"] == source_question_id]
        if len(existing) > 1:
            raise ValueError("Duplicate final records")
        if existing:
            return existing[0]
        previous_attempts = [r for r in self.traces.read("attempts") if r["question_id"] == source_question_id]
        previous_events = [r for r in self.traces.read("events") if r.get("question_id") == source_question_id]
        if previous_events or previous_attempts:
            # Conservative recovery: never reissue a request with uncertain delivery.
            last = previous_attempts[-1] if previous_attempts else None
            if last and last["final_status"] in ("SUBMITTED", "VALIDATED", "ACCEPTED", "FAILED"):
                return self._final(identity, last)
            interrupted = self._attempt_base(identity, (last["attempt"] + 1) if last else 1)
            interrupted.update(final_status="FAILED", infrastructure_error="Interrupted question sealed without resampling",
                               failure_codes=["OTHER"], raw_response=None, artifact=None, artifact_hash=None,
                               runtime_error_type="INTERRUPTED")
            saved = self.traces.append("attempts", interrupted)
            return self._final(identity, saved)

        prompt = self.prompts["baseline" if condition == "A" else "workflow"]
        if hasattr(self.client, "begin_question"):
            self.client.begin_question()
        common = self.prompts["contract"] + "\nJSON schema:\n" + canonical(Annotation.model_json_schema())
        messages = [{"role": "system", "content": common + "\n" + prompt},
                    {"role": "user", "content": canonical(question.model_dump())}]
        retrieved = {}
        max_attempts = 1 if condition in "AB" else 1 + self.settings.max_retries
        for attempt in range(1, max_attempts + 1):
            record = self._attempt_base(identity, attempt)
            start = time.monotonic()
            turns, calls = [], []
            raw = None
            try:
                raw = self._generate(messages, question.question, identity, attempt, turns, calls, retrieved, record)
                record["raw_response"] = raw
                record["tool_calls"] = calls
                self.traces.append("events", {**identity, "attempt": attempt, "event": "draft_saved", "raw_response": raw})
                parsed, parse_error = parse_artifact_json(raw)
                record["artifact"] = parsed
                record["artifact_hash"] = digest(parsed) if parsed is not None else None
                if isinstance(parsed, dict):
                    for key in ("semantic_parse", "retrieved_fact_ids", "golden_context", "python_solution", "unit"):
                        record[key] = parsed.get(key)
                    record["final_answer"] = parsed.get("answer")
                    if normalize_unit(parsed.get("unit", "")) == "year":
                        record["normalized_answer"] = canonical_year(parsed.get("answer"))
                if condition in "AB":
                    record["final_status"] = "SUBMITTED"
                else:
                    context = ValidationContext(question.question_id, question.question, self.facts, self.rules,
                                                set(retrieved), input_parse_error=parse_error)
                    artifact, validations = validate_all(parsed, context)
                    record["validator_results"] = {r.validator_name: r.model_dump(mode="json") for r in validations}
                    record["python_result"] = context.execution["result"] if context.execution else None
                    if artifact is not None and normalize_unit(artifact.unit) == "year" and context.execution:
                        record["normalized_python_result"] = canonical_year(context.execution["result"])
                    record["failure_codes"] = sorted({str(i.failure_code) for r in validations for i in r.issues})
                    feedback = [i.model_dump(mode="json") for r in validations for i in r.issues]
                    judge_result = None
                    if all_pass(validations) and condition == "D":
                        selected = [tool_fact(self.facts.get(e.fact_id)) for e in artifact.selected_evidence]
                        context_messages = judge_messages(question.question, parsed, list(retrieved.values()), selected, self.prompts["judge"])
                        self.traces.append("events", {**identity, "attempt": attempt, "event": "judge_request", "messages": context_messages,
                                                      "request_parameters": self._request_parameters("judge", run_index, [])})
                        judge_turn = self.client.complete(context_messages, [], role="judge", seed=self._seed(run_index))
                        record["judge_usage"] = asdict(judge_turn)
                        self.traces.append("events", {**identity, "attempt": attempt, "event": "judge_response", "response": asdict(judge_turn)})
                        if judge_turn.tool_calls or judge_turn.finish_reason != "stop":
                            raise ValueError("Judge did not submit a complete structured result")
                        judge_result = parse_judge(judge_turn.content)
                        record["judge_result"] = judge_result.model_dump(mode="json")
                        record["failure_codes"] += [str(code) for code in judge_result.failure_codes]
                        feedback += [i.model_dump(mode="json") for i in judge_result.issues]
                    complete = all_pass(validations) if condition == "C" else completion_gate(validations, judge_result)
                    record["feedback"] = feedback
                    record["final_status"] = ("VALIDATED" if condition == "C" else "ACCEPTED") if complete else "FAILED" if attempt == max_attempts else "RETRY_PENDING"
                    if record["final_status"] == "RETRY_PENDING":
                        messages.append({"role": "user", "content": canonical({"validation_feedback": feedback, "instruction": "Return a complete corrected annotation. Use the same workflow and data contract."})})
            except Exception as exc:
                # Infrastructure/invalid judge output is not a semantic failure and is never silently retried.
                error = str(exc)
                if os.getenv("OPENAI_API_KEY"):
                    error = error.replace(os.environ["OPENAI_API_KEY"], "[REDACTED]")
                # Provider error bodies can echo credentials. Preserve type, not raw body.
                if type(exc).__module__.startswith("openai"):
                    error = "Provider request failed; see error type and request event. No automatic retry."
                record.update(final_status="FAILED", infrastructure_error=f"{type(exc).__name__}: {error[:500]}")
                record["runtime_error_type"] = getattr(exc, "kind", "MODEL_FAILURE")
                if getattr(exc, "diagnostics", None) is not None:
                    self.traces.append("events", {**identity, "attempt": attempt,
                        "event": "provider_failure_diagnostics", "diagnostics": exc.diagnostics})
                self.traces.append("events", {**identity, "attempt": attempt, "event": "runtime_error",
                                              "runtime_error_type": record["runtime_error_type"], "error": record["infrastructure_error"]})
                record["failure_codes"] = sorted(set(record["failure_codes"] + ["OTHER"]))
            record["tool_calls"] = calls
            record["candidate_fact_ids"] = sorted(retrieved)
            record["input_tokens"] = sum_usage(turns, "input_tokens")
            record["output_tokens"] = sum_usage(turns, "output_tokens")
            record["latency_ms"] = round((time.monotonic() - start) * 1000)
            saved = self.traces.append("attempts", record)
            if record["final_status"] != "RETRY_PENDING":
                return self._final(identity, saved)
        raise AssertionError("Attempt bound violated")

    def _seed(self, run_index):
        return self.settings.model.base_seed + run_index - 1 if self.settings.model.supports_seed else None

    def _request_parameters(self, role, run_index, tools=None):
        if hasattr(self.client, "describe_completion_request"):
            return self.client.describe_completion_request(role, self._seed(run_index), tools or [])
        if hasattr(self.client, "describe_request"):
            return self.client.describe_request(role, self._seed(run_index))
        return {"provider": self.settings.model.provider, "settings": self.settings.model.model_dump(), "role": role,
                "seed": self._seed(run_index)}

    def _attempt_base(self, identity, attempt):
        return {**identity, "attempt": attempt, "model": self.settings.model.generator_model,
                "model_version": self.settings.model.generator_version, "prompt_version": digest(self.prompts),
                "temperature": self.settings.model.generator_temperature, "max_tokens": self.settings.model.max_tokens,
                "seed": self._seed(identity["run_index"]), "semantic_parse": None, "tool_calls": [],
                "retrieved_fact_ids": [], "golden_context": None, "python_solution": None, "python_result": None,
                "final_answer": None, "normalized_answer": None, "normalized_python_result": None,
                "unit": None, "validator_results": {}, "judge_result": None,
                "failure_codes": [], "final_status": "GENERATING", "input_tokens": None, "output_tokens": None,
                "latency_ms": None, "artifact": None, "artifact_hash": None, "raw_response": None,
                "generator_responses": [], "feedback": [], "judge_usage": None, "runtime_error_type": None,
                "runtime": getattr(self.client, "runtime", {}), "resolved_model_config": self.settings.model.model_dump()}

    def _generate(self, messages, question, identity, attempt, turns, calls, retrieved, record):
        two_phase = bool(getattr(self.client, "two_phase_generator", False))
        ready = two_phase and finalization_ready(question, retrieved)
        for step in range(self.settings.max_model_calls_per_attempt):
            tools = [] if ready else [search_tool_schema()]
            self.traces.append("events", {**identity, "attempt": attempt, "event": "generator_request", "step": step, "messages": messages,
                                          "request_parameters": self._request_parameters("generator", identity["run_index"], tools),
                                          "generator_phase": "structured_finalization" if ready else "tool_retrieval"})
            turn = self.client.complete(messages, tools, role="generator", seed=self._seed(identity["run_index"]))
            turns.append(turn)
            record["generator_responses"].append(asdict(turn))
            self.traces.append("events", {**identity, "attempt": attempt, "event": "generator_response", "step": step, "response": asdict(turn)})
            messages.append(turn.message())
            if not turn.tool_calls:
                # Truncation remains an actual submitted bad output in A/B; C/D may validate/retry it.
                return turn.content or ""
            if len(calls) + len(turn.tool_calls) > self.settings.max_tool_calls_per_attempt:
                raise RuntimeError("Tool call budget exceeded")
            for call in turn.tool_calls:
                started = time.monotonic()
                function = call.get("function", {})
                try:
                    if function.get("name") != "search_financial_facts":
                        raise ValueError("Unknown tool name")
                    args = SearchRequest.model_validate_json(function["arguments"])
                    output = self.facts.search_financial_facts(**args.model_dump())
                except (ValueError, KeyError, TypeError) as exc:
                    output = {"success": False, "candidates": [], "error": str(exc), "missing_information": [],
                              "retry_suggestion": "Use the published tool argument schema.", "recommended_next_action": "refine_query"}
                for candidate in output["candidates"]:
                    retrieved[candidate["fact_id"]] = candidate
                trace = {"call_id": call["id"], "name": function.get("name"), "arguments": function.get("arguments"),
                         "result": output, "latency_ms": round((time.monotonic() - started) * 1000)}
                calls.append(trace)
                self.traces.append("events", {**identity, "attempt": attempt, "event": "tool_result", **trace})
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": canonical(output)})
            if two_phase and not ready and finalization_ready(question, retrieved):
                ready = True
                self.traces.append("events", {**identity, "attempt": attempt,
                    "event": "generator_phase_transition", "phase": "structured_finalization",
                    "reason": "Retrieved reported facts cover every explicit question year"})
        raise RuntimeError("Model interaction budget exceeded without final annotation")

    def _final(self, identity, attempt):
        return self.traces.append("finals", {**identity, "attempt": attempt["attempt"], "final_status": attempt["final_status"],
                                 "artifact": attempt["artifact"], "artifact_hash": attempt["artifact_hash"],
                                 "normalized_answer": attempt.get("normalized_answer"),
                                 "normalized_python_result": attempt.get("normalized_python_result"),
                                 "failure_codes": attempt["failure_codes"], "attempt_record_hash": attempt["record_hash"]})
