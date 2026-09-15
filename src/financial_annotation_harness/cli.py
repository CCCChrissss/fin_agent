"""Repository commands; live runs opt in and Test is freeze-gated."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from .config import load_rules, load_settings
from .dataset import derive_dataset, inspect_dataset, stratified_split, verify_derived, verify_gold_python
from .demo import run_demo
from .evaluation import evaluate_experiment, evaluate_scope
from .facts import FactRepository
from .governance import create_freeze, environment_manifest, project_hashes, verify_freeze, validate_selection
from .io_utils import digest, file_hash, read_json, read_jsonl, timestamp, write_new_json
from .model_client import create_provider, ProviderError
from .runner import AnnotationRunner
from .schemas import QuestionInput
from .trace import TraceStore


def load_prompts(root: Path) -> dict:
    return {name: (root / "prompts" / f"{filename}.md").read_text(encoding="utf-8")
            for name, filename in (("baseline", "baseline"), ("workflow", "workflow"), ("judge", "judge_rubric"), ("contract", "contract"))}


def safe_output(root: Path, value: str) -> Path:
    path = (root / value).resolve()
    if not path.is_relative_to(root) or path == root or path.is_relative_to(root / "data"):
        raise ValueError("Output must be inside the project and outside source data/")
    return path


def parser():
    p = argparse.ArgumentParser(description="Financial Annotation Harness (offline by default)")
    p.add_argument("--root", type=Path, default=Path.cwd())
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("audit")
    pre = sub.add_parser("ollama-preflight")
    pre.add_argument("--config", default="config/screening.example.yaml")
    pre.add_argument("--output", required=True)
    for name in ("screen", "smoke"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--config", default="config/screening.example.yaml")
        cmd.add_argument("--output", required=True)
        cmd.add_argument("--live", action="store_true")
        cmd.add_argument("--dry-run", action="store_true")
        cmd.add_argument("--resume", action="store_true")
    screening_eval = sub.add_parser("evaluate-screening")
    screening_eval.add_argument("--experiment", nargs="+", required=True)
    screening_eval.add_argument("--output", required=True)
    screening_eval.add_argument("--reviews", type=Path)
    v = sub.add_parser("verify-gold-python")
    v.add_argument("--output", required=True)
    sub.add_parser("derive")
    s = sub.add_parser("split")
    s.add_argument("--seed", type=int, default=20260915)
    f = sub.add_parser("freeze")
    f.add_argument("--config", default="config/experiment.example.yaml")
    f.add_argument("--reviewer", required=True)
    f.add_argument("--attestation", required=True, choices=["gold-and-rules-reviewed"])
    d = sub.add_parser("demo")
    d.add_argument("--output", default="artifacts/runtime/synthetic-demo")
    r = sub.add_parser("run")
    r.add_argument("--config", default="config/experiment.example.yaml")
    r.add_argument("--partition", choices=["development", "test"], default="development")
    r.add_argument("--output", required=True)
    r.add_argument("--live", action="store_true")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--resume", action="store_true")
    e = sub.add_parser("evaluate")
    e.add_argument("--experiment", required=True)
    e.add_argument("--output", required=True)
    e.add_argument("--reviews", type=Path)
    o = sub.add_parser("evaluate-scope")
    o.add_argument("--input", type=Path, required=True)
    o.add_argument("--output", required=True)
    return p


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    root = args.root.resolve(strict=True)
    source = root / "data/financial_qa_gold_dataset_v2.xlsx"
    before = file_hash(source) if source.exists() else None
    try:
        answer = dispatch(args, root, source)
        print(json.dumps(answer, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, ProviderError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if before and file_hash(source) != before:
            raise RuntimeError("Original Excel changed during command")


def dispatch(args, root, source):
    if args.command == "ollama-preflight":
        from .ollama_provider import inventory
        from .runtime_environment import environment_snapshot
        from .screening import load_screening
        config = load_screening(root / args.config)
        report = {"hardware": environment_snapshot(), "experiment_kind": "preflight"}
        try:
            report.update(inventory(config.settings.model.base_url))
            tags = {m["name"] for m in report["models"]}
            report["missing_models"] = [c.model_tag for c in config.candidates if c.model_tag not in tags]
        except ProviderError as exc:
            report["error_type"] = exc.kind
            report["missing_models"] = None
        report["note"] = "One snapshot only; no downloads or polling. Notify the researcher after manual downloads finish."
        write_new_json(safe_output(root, args.output), report)
        return report
    if args.command == "smoke":
        from .screening import load_screening
        from .smoke import run_smoke
        from .runtime_environment import environment_snapshot
        config = load_screening(root / args.config)
        if args.dry_run:
            return {"experiment_kind": "smoke", "synthetic_questions_per_model": 2, "judge_requests_per_model": 1, "no_API_called": True}
        if not args.live or args.resume:
            raise ValueError("Smoke requires --live and a new output directory; no automatic resume")
        for c in config.candidates:
            config.candidate_settings(c).require_live()
        return run_smoke(config, load_rules(root), load_prompts(root), safe_output(root, args.output), environment_snapshot())
    if args.command == "audit":
        report = inspect_dataset(source)["report"]
        if report["errors"]:
            raise ValueError(report["errors"])
        return report
    if args.command == "derive":
        return {"derived_directory": str(derive_dataset(source, root / "artifacts"))}
    if args.command == "verify-gold-python":
        report = verify_gold_python(source, load_rules(root))
        write_new_json(safe_output(root, args.output), report)
        if report["execution_pass_count"] != report["question_count"] or report["answer_match_count"] != report["question_count"]:
            raise ValueError("Gold Python compatibility audit failed; see the saved report")
        return {k: v for k, v in report.items() if k != "results"}
    if args.command == "demo":
        report = run_demo(safe_output(root, args.output), load_rules(root), load_prompts(root))
        return {"mode": report["mode"], "question_runs": report["observed_question_runs"], "pending_reviews": report["pending_review_count"],
                "output": args.output, "note": "Synthetic software test only. Full report under evaluation/."}
    if args.command == "evaluate-scope":
        report = evaluate_scope(read_jsonl(args.input))
        write_new_json(safe_output(root, args.output), report)
        return report
    derived = root / "artifacts/derived" / file_hash(source)
    source_manifest = verify_derived(source, derived)
    metadata = read_jsonl(derived / "question_metadata.jsonl")
    if args.command == "split":
        split = stratified_split(metadata, source_manifest["sha256"], args.seed)
        target = root / "artifacts/dataset_split.json"
        if target.exists():
            if read_json(target) != split:
                raise ValueError("Existing split differs; never silently replace a split")
        else:
            write_new_json(target, split)
        return split
    split = read_json(root / "artifacts/dataset_split.json")
    if split != stratified_split(metadata, source_manifest["sha256"], split["seed"]):
        raise ValueError("Split does not match its reproducible algorithm")
    if args.command == "freeze":
        settings = load_settings(root / args.config)
        if settings.split_seed != split["seed"]:
            raise ValueError("Config and split seed differ")
        return create_freeze(root, source_manifest, split, settings, root / "artifacts/freeze_manifest.json",
                             reviewer=args.reviewer, attestation=args.attestation)
    aliases = yaml.safe_load((root / "config/concept_aliases.yaml").read_text(encoding="utf-8"))
    if args.command in ("screen", "evaluate-screening"):
        from .screening import load_screening, run_screening, screening_schedule, validate_parent
        from .screening_evaluation import evaluate_screenings
        from .runtime_environment import environment_snapshot
        provenance = {"source_manifest_hash": digest(source_manifest), "split_hash": digest(split), "project_hashes": project_hashes(root)}
        config = load_screening(root / args.config) if args.command == "screen" else None
        if config:
            schedule = screening_schedule(config, split)
            validate_parent(config, root, provenance)
            if args.dry_run:
                return {"experiment_kind": "screening", "condition": "B", "partition": "development", "question_runs": len(schedule),
                        "stage": config.stage, "no_API_called": True, "winner": None}
            if not args.live:
                raise ValueError("Screening inference requires explicit --live")
        language = config.settings.language if config else read_json((root / args.experiment[0]) / "manifest.json")["screening_config"]["settings"]["language"]
        public_ids = {m["question_id"]: m["public_question_id"] for m in metadata if m["question_id"] in split["development"]}
        allowed = set(public_ids.values())
        inputs = {q["question_id"]: q for q in read_jsonl(derived / "question_inputs.jsonl") if q["question_id"] in allowed}
        questions = {qid: QuestionInput(question_id=pid, question=inputs[pid][language], language=language) for qid, pid in public_ids.items()}
        repo = FactRepository(derived / "financial_facts.sqlite", aliases, config.settings.search_top_k if config else 12)
        if config:
            return run_screening(config, split, questions, repo, load_rules(root), load_prompts(root), safe_output(root, args.output),
                                 provenance, environment_snapshot(), resume=args.resume)
        directories = [(root / p).resolve(strict=True) for p in args.experiment]
        for directory in directories:
            manifest = read_json(directory / "manifest.json")
            if any(manifest.get(k) != v for k, v in provenance.items()):
                raise ValueError("Screening evaluation source/code differs from experiment")
        return evaluate_screenings(directories, read_jsonl(derived / "gold_annotations.jsonl"), questions, repo, load_rules(root), split,
                                   safe_output(root, args.output), read_jsonl(args.reviews) if args.reviews else None)
    if args.command == "evaluate":
        directory = (root / args.experiment).resolve(strict=True)
        manifest = read_json(directory / "manifest.json")
        if manifest["source_manifest_hash"] != digest(source_manifest):
            raise ValueError("Evaluation source differs from experiment source")
        if manifest["project_hashes"] != project_hashes(root):
            raise ValueError("Evaluation code/rules differ from the experiment snapshot")
        repo = FactRepository(derived / "financial_facts.sqlite", aliases)
        language = manifest["settings"]["language"]
        questions = [{"question_id": q["question_id"], "question": q[language], "language": language}
                     for q in read_jsonl(derived / "question_inputs.jsonl")]
        return evaluate_experiment(directory, read_jsonl(derived / "gold_annotations.jsonl"), questions, repo, load_rules(root),
                                   safe_output(root, args.output), read_jsonl(args.reviews) if args.reviews else None)
    settings = load_settings(root / args.config)
    if settings.split_seed != split["seed"]:
        raise ValueError("Config and split seed differ")
    ids = split[args.partition]
    expected = [{"run_index": r, "condition": c, "question_id": q} for r in (1, 2, 3) for c in "ABCD" for q in ids]
    if args.dry_run:
        return {"partition": args.partition, "question_runs": len(expected), "conditions": settings.conditions,
                "live_calls_allowed": settings.max_live_calls, "no_API_called": True, "source_verified": True,
                "test_requires_human_freeze": True}
    if not args.live:
        raise ValueError("Use demo for offline verification; run requires explicit --live")
    settings.require_live()
    validate_selection(root, settings)
    if args.partition == "test":
        verify_freeze(root, source_manifest, split, settings, read_json(root / "artifacts/freeze_manifest.json"))
    output = safe_output(root, args.output)
    manifest = {"schema_version": "1.0", "experiment_id": output.name, "experiment_kind": "main", "mode": "live",
                "partition": args.partition, "expected_runs": expected, "settings": settings.model_dump(),
                "source_manifest_hash": digest(source_manifest), "split_hash": digest(split), "project_hashes": project_hashes(root)}
    if output.exists():
        if not args.resume:
            raise FileExistsError("Experiment already exists; explicit --resume required")
        old = read_json(output / "manifest.json")
        if any(old.get(k) != v for k, v in manifest.items()):
            raise ValueError("Cannot resume with changed controls or data")
    else:
        if args.resume:
            raise ValueError("Cannot resume a nonexistent experiment")
        output.mkdir(parents=True)
        write_new_json(output / "manifest.json", {**manifest, "created_at": timestamp(), "environment": environment_manifest()})
    inputs = {q["question_id"]: q for q in read_jsonl(derived / "question_inputs.jsonl")}
    public_ids = {m["question_id"]: m["public_question_id"] for m in metadata}
    client = create_provider(settings, allow_live=True)
    if settings.model.provider == "ollama":
        from .runtime_environment import environment_snapshot
        current_runtime = {"runtime": client.runtime, "hardware": environment_snapshot()}
        if args.partition == "test":
            frozen = read_json(root / "artifacts/freeze_manifest.json")
            if any(frozen.get(k) != v for k, v in current_runtime.items()):
                client.close()
                raise ValueError("Frozen runtime/hardware changed")
        runtime_path = output / "runtime.json"
        if runtime_path.exists():
            if read_json(runtime_path) != current_runtime:
                client.close()
                raise ValueError("Cannot resume changed runtime/hardware")
        else:
            write_new_json(runtime_path, current_runtime)
    if args.resume:
        client.calls = sum(1 for path in output.glob("run_*/[ABCD]/events.jsonl") for event in read_jsonl(path)
                           if event["event"] in ("generator_request", "judge_request"))
    repo = FactRepository(derived / "financial_facts.sqlite", aliases, settings.search_top_k)
    for run_index in (1, 2, 3):
        for condition in "ABCD":
            with TraceStore(output / f"run_{run_index:02d}" / condition) as store:
                runner = AnnotationRunner(settings, repo, load_rules(root), load_prompts(root), client, store)
                for qid in ids:
                    raw = inputs[public_ids[qid]]
                    question = QuestionInput(question_id=raw["question_id"], question=raw[settings.language], language=settings.language)
                    runner.run_question(question, source_question_id=qid, condition=condition, run_index=run_index, experiment_id=output.name)
    if hasattr(client, "verify_identity"):
        client.verify_identity()
    if hasattr(client, "close"):
        client.close()
    return {"output": str(output), "question_runs": len(expected), "API_calls_attempted": client.calls,
            "note": "Records saved; correctness requires independent offline evaluation."}


if __name__ == "__main__":
    raise SystemExit(main())
