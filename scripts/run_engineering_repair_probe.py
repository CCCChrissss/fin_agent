"""Ten-run Dev-only probe for the engineering repair revision."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))

from dev_prompt_candidates import generator_prompts, judge_prompt
from financial_annotation_harness.cli import load_prompts
from financial_annotation_harness.config import load_rules, load_settings
from financial_annotation_harness.dataset import verify_derived
from financial_annotation_harness.facts import FactRepository
from financial_annotation_harness.governance import project_hashes, review_provenance
from financial_annotation_harness.io_utils import digest, file_hash, read_json, read_jsonl, timestamp, write_new_json
from financial_annotation_harness.runner import AnnotationRunner
from financial_annotation_harness.runtime_environment import environment_snapshot
from financial_annotation_harness.schemas import Annotation, QuestionInput
from financial_annotation_harness.trace import TraceStore
from run_dev_prompt_v2 import CandidateProvider

TARGET_IDS = {'CP03', 'GR03', 'LG01', 'LG03', 'RT04'}
OUT = None


class EngineeringProvider(CandidateProvider):
    structured_generator = False
    two_phase_generator = False

    def describe_request(self, role, seed):
        payload = super().describe_request(role, seed)
        if role == 'generator' and self.structured_generator:
            payload['format'] = Annotation.model_json_schema()
        return payload

    def describe_completion_request(self, role, seed, tools):
        payload = super().describe_request(role, seed)
        if role == 'generator' and self.two_phase_generator and not tools:
            payload['format'] = Annotation.model_json_schema()
        return payload


def probe_profile(*, qwen=False, only_cp03=False, structured_generator=False, two_phase=False,
                  repeat_penalty=False, comparison_feedback=False, year_normalization=False,
                  grounding_feedback=False, unified_comparison_repair=False,
                  canonical_final_trace=False):
    config = ROOT / 'config' / ('experiment.gemma4.repeat-penalty.probe.json' if repeat_penalty else
                                'experiment.qwen35-9b.probe.json' if qwen else
                                'experiment.ai-assisted.v1.json')
    if canonical_final_trace:
        name = ('gemma-canonical-final-trace-cp03-probe' if only_cp03 else
                'gemma-canonical-final-trace-five-case-probe')
    elif unified_comparison_repair:
        name = ('gemma-unified-comparison-repair-cp03-probe' if only_cp03 else
                'gemma-unified-comparison-repair-five-case-probe')
    elif grounding_feedback:
        name = ('gemma-year-normalization-grounding-feedback-cp03-probe' if only_cp03 else
                'gemma-year-normalization-grounding-feedback-five-case-probe')
    elif year_normalization:
        name = 'gemma-year-normalization-cp03-probe' if only_cp03 else 'gemma-year-normalization-five-case-probe'
    elif repeat_penalty and comparison_feedback:
        name = ('gemma-repeat-penalty-comparison-feedback-cp03-probe' if only_cp03 else
                'gemma-repeat-penalty-comparison-feedback-five-case-probe')
    elif comparison_feedback:
        name = 'gemma-comparison-feedback-cp03-probe' if only_cp03 else 'gemma-comparison-feedback-five-case-probe'
    elif repeat_penalty:
        name = 'gemma-repeat-penalty-cp03-probe' if only_cp03 else 'gemma-repeat-penalty-five-case-probe'
    elif two_phase:
        name = 'gemma-two-phase-cp03-probe' if only_cp03 else 'gemma-two-phase-five-case-probe'
    elif structured_generator:
        name = 'gemma-structured-cp03-probe' if only_cp03 else 'gemma-structured-five-case-probe'
    elif qwen:
        name = 'qwen35-cp03-probe' if only_cp03 else 'qwen35-five-case-probe'
    else:
        name = 'cp03-json-feedback-probe' if only_cp03 else 'live-probe'
    return config, ROOT / 'outputs/engineering-repair-v1' / name


def schedule(split_path: Path, target_ids=None) -> list[dict]:
    split = read_json(split_path)
    target_ids = TARGET_IDS if target_ids is None else set(target_ids)
    development = set(split['development'])
    test = set(split['test'])
    if not target_ids or not target_ids <= development or target_ids & test:
        raise ValueError('Probe targets must be Development-only')
    return [{'run_index': 1, 'condition': condition, 'question_id': question_id}
            for condition in 'CD' for question_id in sorted(target_ids)]


def immutable(path: Path, value: dict):
    if path.exists():
        if read_json(path) != value:
            raise ValueError(f'Cannot resume changed provenance: {path}')
    else:
        write_new_json(path, value)


def status(phase: str, **details):
    value = {'phase': phase, 'updated_at': timestamp(), 'pid': os.getpid(), **details}
    temp = OUT / 'status.tmp'
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(OUT / 'status.json')
    print(json.dumps(value, ensure_ascii=False), flush=True)


def evaluate():
    output = OUT / 'evaluation-mechanical'
    if output.exists():
        if not (output / 'aggregate_metrics.json').exists():
            raise ValueError('Partial evaluation directory preserved for inspection')
        return
    subprocess.run([sys.executable, '-B', '-m', 'financial_annotation_harness', 'evaluate',
                    '--experiment', str(OUT), '--output', str(output)], cwd=ROOT,
                   env={**os.environ, 'PYTHONPATH': str(ROOT / 'src'), 'PYTHONIOENCODING': 'utf-8'}, check=True)


def main():
    global OUT
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--only-cp03', action='store_true')
    parser.add_argument('--qwen', action='store_true')
    parser.add_argument('--structured-generator', action='store_true')
    parser.add_argument('--two-phase', action='store_true')
    parser.add_argument('--repeat-penalty', action='store_true')
    parser.add_argument('--comparison-feedback', action='store_true')
    parser.add_argument('--year-normalization', action='store_true')
    parser.add_argument('--grounding-feedback', action='store_true')
    parser.add_argument('--unified-comparison-repair', action='store_true')
    parser.add_argument('--canonical-final-trace', action='store_true')
    args = parser.parse_args()
    split_path = ROOT / 'artifacts/dataset_split.json'
    split = read_json(split_path)
    targets = {'CP03'} if args.only_cp03 else TARGET_IDS
    if sum((args.qwen, args.structured_generator, args.two_phase, args.repeat_penalty)) > 1:
        raise ValueError('Compare one model or one boundary change at a time')
    config_path, OUT = probe_profile(qwen=args.qwen, only_cp03=args.only_cp03,
                                    structured_generator=args.structured_generator, two_phase=args.two_phase,
                                    repeat_penalty=args.repeat_penalty,
                                    comparison_feedback=args.comparison_feedback,
                                    year_normalization=args.year_normalization,
                                    grounding_feedback=args.grounding_feedback,
                                    unified_comparison_repair=args.unified_comparison_repair,
                                    canonical_final_trace=args.canonical_final_trace)
    expected = schedule(split_path, targets)
    settings = load_settings(config_path)
    source = ROOT / 'data/financial_qa_gold_dataset_v2.xlsx'
    derived = ROOT / 'artifacts/derived' / file_hash(source)
    source_manifest = verify_derived(source, derived)
    prompts = generator_prompts(load_prompts(ROOT))
    prompts['judge'] = judge_prompt([{'role': 'system', 'content': prompts['judge']}])[0]['content']
    manifest = {
        'schema_version': '1.0', 'experiment_id': OUT.name, 'experiment_kind': 'main',
        'study_stage': ('canonical_final_trace_probe_v1' if args.canonical_final_trace else
                        'unified_comparison_repair_probe_v1' if args.unified_comparison_repair else
                        'comparison_grounding_feedback_probe_v1' if args.grounding_feedback else
                        'year_normalization_probe_v1' if args.year_normalization else
                        'comparison_feedback_probe_v2' if args.comparison_feedback else
                        'cp03_json_feedback_probe_v1' if args.only_cp03 else 'engineering_repair_probe_v1'),
        'mode': 'live', 'partition': 'development',
        'expected_runs': expected, 'settings': settings.model_dump(),
        'source_manifest_hash': digest(source_manifest), 'split_hash': digest(split),
        'project_hashes': project_hashes(ROOT),
        'review_provenance': review_provenance(ROOT, settings, source_manifest),
        'resolved_prompts': prompts, 'test_execution_allowed': False,
        'scope': ('CP03 only, conditions C/D, one run; diagnostic only, no inferential claim' if args.only_cp03
                  else 'Five known Dev failure cases, conditions C/D, one run; diagnostic only, no inferential claim'),
        'parent_manifest_hash': file_hash(ROOT / 'outputs/dev-prompt-v2/full-dev/manifest.json'),
        'generator_output_format': ('post_retrieval_annotation_json_schema' if args.two_phase else
                                    'annotation_json_schema' if args.structured_generator else 'prompt_only'),
        'parameter_candidate': {'repeat_penalty': settings.model.repeat_penalty} if args.repeat_penalty else None,
        'validator_feedback_candidate': 'comparison_feedback_v2' if args.comparison_feedback else None,
        'year_normalization_candidate': 'roc_gregorian_equivalence_v1' if args.year_normalization else None,
        'grounding_feedback_candidate': 'comparison_binding_feedback_v1' if args.grounding_feedback else None,
        'unified_comparison_repair_candidate': 'unified_comparison_repair_v1' if args.unified_comparison_repair else None,
        'canonical_final_trace_candidate': 'canonical_year_finals_v1' if args.canonical_final_trace else None,
    }
    if not args.live:
        print(json.dumps({'question_runs': len(expected), 'live_calls': 0, 'targets': sorted(targets)}))
        return
    settings.require_live()
    if OUT.exists() and not args.resume:
        raise FileExistsError('Probe output exists; explicit --resume required')
    if not OUT.exists() and args.resume:
        raise ValueError('Cannot resume a nonexistent probe')
    OUT.mkdir(parents=True, exist_ok=True)
    immutable(OUT / 'manifest.json', manifest)
    client = EngineeringProvider(settings, allow_live=True)
    client.structured_generator = args.structured_generator
    client.two_phase_generator = args.two_phase
    try:
        immutable(OUT / 'runtime.json', {'runtime': client.runtime, 'hardware': environment_snapshot()})
        inputs = {q['question_id']: q for q in read_jsonl(derived / 'question_inputs.jsonl')}
        public_ids = {q['question_id']: q['public_question_id'] for q in read_jsonl(derived / 'question_metadata.jsonl')}
        aliases = yaml.safe_load((ROOT / 'config/concept_aliases.yaml').read_text(encoding='utf-8'))
        repo = FactRepository(derived / 'financial_facts.sqlite', aliases, settings.search_top_k)
        client.calls = sum(e['event'] in ('generator_request', 'judge_request')
                           for p in OUT.glob('run_*/[CD]/events.jsonl') for e in read_jsonl(p))
        total = len(expected)
        for condition in 'CD':
            with TraceStore(OUT / 'run_01' / condition) as store:
                runner = AnnotationRunner(settings, repo, load_rules(ROOT), prompts, client, store,
                    trace_context={'study_stage': manifest['study_stage']})
                for question_id in sorted(targets):
                    raw = inputs[public_ids[question_id]]
                    question = QuestionInput(question_id=raw['question_id'], question=raw[settings.language], language=settings.language)
                    completed = sum(len(read_jsonl(p)) for p in OUT.glob('run_*/[CD]/finals.jsonl'))
                    status('GENERATION', completed=completed, total=total,
                           current={'condition': condition, 'question_id': question_id})
                    runner.run_question(question, source_question_id=question_id, condition=condition,
                                        run_index=1, experiment_id=OUT.name)
        client.verify_identity()
    finally:
        client.close()
    finals = [r for p in OUT.glob('run_*/[CD]/finals.jsonl') for r in read_jsonl(p)]
    actual = {(r['run_index'], r['condition'], r['question_id']) for r in finals}
    planned = {(r['run_index'], r['condition'], r['question_id']) for r in expected}
    if len(finals) != len(expected) or actual != planned:
        raise ValueError('Incomplete or duplicate probe results')
    status('EVALUATING', completed=len(expected), total=len(expected))
    evaluate()
    status('COMPLETE', completed=len(expected), total=len(expected),
           pending_semantic_reviews=read_json(OUT / 'evaluation-mechanical/aggregate_metrics.json')['pending_review_count'])


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        if OUT is not None and OUT.exists() and (OUT / 'manifest.json').exists():
            status('STOPPED_WITH_ERROR', error=f'{type(exc).__name__}: {exc}')
            (OUT / 'error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        raise
