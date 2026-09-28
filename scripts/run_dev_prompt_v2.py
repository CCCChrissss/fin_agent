"""Bounded 144-run Development candidate; never freezes or executes Test."""
import argparse
from dataclasses import asdict
import html
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback
import uuid
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from financial_annotation_harness.cli import load_prompts
from financial_annotation_harness.config import load_settings, load_rules
from financial_annotation_harness.dataset import verify_derived
from financial_annotation_harness.facts import FactRepository, tool_fact
from financial_annotation_harness.governance import project_hashes, review_provenance
from financial_annotation_harness.io_utils import read_json, read_jsonl, write_new_json, write_new_jsonl, file_hash, digest, timestamp
from financial_annotation_harness.ollama_provider import OllamaProvider
from financial_annotation_harness.runner import AnnotationRunner
from financial_annotation_harness.schemas import QuestionInput
from financial_annotation_harness.trace import TraceStore
from financial_annotation_harness.runtime_environment import environment_snapshot
from dev_prompt_candidates import generator_prompts, judge_prompt
from probe_dev_judge import probe_schema
from repair_offline_reviews import review_schema
from complete_ai_study import review_messages, parse_review, REVIEW_FIELDS, RUBRIC

OUT = None


def dev_profile(*, candidate_v3=False, candidate_v4=False):
    if candidate_v4:
        return (ROOT / 'config/experiment.dev-candidate-v3.json',
                ROOT / 'outputs/dev-prompt-v4/full-dev-v4', 'development_year_fix_v4')
    if candidate_v3:
        return (ROOT / 'config/experiment.dev-candidate-v3.json',
                ROOT / 'outputs/dev-prompt-v3/full-dev-v3', 'development_candidate_v3')
    return (ROOT / 'config/experiment.ai-assisted.v1.json',
            ROOT / 'outputs/dev-prompt-v2/full-dev', 'development_candidate_v2')


def schedule(split):
    ids = sorted(split['development'])
    if len(ids) != 12 or len(set(ids)) != 12 or set(ids) & set(split['test']):
        raise ValueError('Expected twelve distinct Development questions, disjoint from Test')
    return [{'run_index': r, 'condition': c, 'question_id': q}
            for r in (1, 2, 3) for c in 'ABCD' for q in ids]


class CandidateProvider(OllamaProvider):
    offline = False

    def describe_request(self, role, seed):
        payload = super().describe_request(role, seed)
        if role == 'judge':
            payload['format'] = review_schema() if self.offline else probe_schema()
        return payload


def immutable(path, value):
    if path.exists():
        if read_json(path) != value:
            raise ValueError(f'Provenance drift: {path}')
    else:
        write_new_json(path, value)


def status(phase, **kwargs):
    value = {'phase': phase, 'updated_at': timestamp(), 'pid': os.getpid(), **kwargs}
    temp = OUT / 'status.tmp'
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    try:
        temp.replace(OUT / 'status.json')
    except PermissionError:
        # UI state is noncritical; immutable experiment journals still fail closed.
        write_new_json(OUT / f'status-event-{uuid.uuid4().hex}.json', value)
    print(json.dumps(value, ensure_ascii=False), flush=True)
    try:
        render_report(value)
    except PermissionError as exc:
        print(json.dumps({'ui_warning': type(exc).__name__, 'experiment_continues': True}), flush=True)


def render_report(state):
    columns = ['e2e_accuracy', 'answer_accuracy', 'evidence_f1', 'python_execution_rate',
               'python_answer_consistency', 'first_pass_accuracy', 'recovery_rate']
    sections = []
    for title, path in [('原版 Dev（修復後離線評分）', ROOT / 'outputs/offline-repair-v1/dev/evaluation/aggregate_metrics.json'),
                        ('候選 v2 Dev', OUT / 'evaluation-ai/aggregate_metrics.json')]:
        if not path.exists():
            continue
        data = read_json(path)
        rows = []
        for condition, metrics in data['metrics'].items():
            values = []
            for key in columns:
                item = metrics[key]
                values.append('待定' if item['mean'] is None else f"{item['mean']:.1%} ± {(item['sample_sd'] or 0):.1%}")
            rows.append('<tr><th>' + condition + '</th>' + ''.join('<td>'+v+'</td>' for v in values) + '</tr>')
        sections.append(f'<h2>{title}</h2><p>完成 {data["observed_question_runs"]}/{data["expected_question_runs"]}；待評 {data["pending_review_count"]}。三次 run 的 mean ± sample SD。</p><table><tr><th>組別</th>' + ''.join('<th>'+k+'</th>' for k in columns) + '</tr>' + ''.join(rows) + '</table>')
    page = '<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>Dev Prompt v2 驗證</title><style>body{font:16px/1.7 Microsoft JhengHei,sans-serif;margin:32px;color:#18314b}table{border-collapse:collapse}td,th{padding:12px;border:1px solid #ccd6e0}th{background:#edf3fa}pre{white-space:pre-wrap}</style><h1>Dev Prompt v2：12 題 × A/B/C/D × 3 次</h1><pre>'
    page += html.escape(json.dumps(state, ensure_ascii=False, indent=2)) + '</pre>' + ''.join(sections)
    page += '<p>僅 Development 候選版驗證。A/B/C/D 定義、模型、參數與 Retry 上限維持；B/C/D 更新 Workflow，D 更新 Judge 指引及 JSON schema。這是組合改善驗證，不能單獨歸因於 prompt。離線評分沿用原 rubric 與結構化格式，由同模型獨立 context 執行，非人工審核；仍有同模型偏差。先前 Test 已使用過，因此後續改版不得宣稱其為全新未見測試集。本流程不執行 Test、不自動 Freeze。</p></html>'
    tmp = OUT / 'report.tmp'
    tmp.write_text(page, encoding='utf-8')
    tmp.replace(OUT / 'report.html')


def evaluate(output, reviews=None):
    if output.exists():
        if not (output / 'aggregate_metrics.json').exists():
            raise ValueError('Incomplete evaluation directory; preserve for inspection')
        return
    args = [sys.executable, '-B', '-m', 'financial_annotation_harness', 'evaluate',
            '--experiment', str(OUT), '--output', str(output)]
    if reviews:
        args += ['--reviews', str(reviews)]
    subprocess.run(args, cwd=ROOT, env={**os.environ, 'PYTHONPATH': str(ROOT / 'src'),
                   'PYTHONIOENCODING': 'utf-8'}, check=True)


def offline_review(settings, repo):
    evaluate(OUT / 'evaluation-mechanical')
    queue = read_jsonl(OUT / 'evaluation-mechanical/review_queue.jsonl')
    folder = OUT / 'offline-ai-review'
    folder.mkdir(exist_ok=True)
    provenance = {'rubric': RUBRIC, 'schema': review_schema(), 'model': settings.model.model_dump(),
                  'review_kind': 'ai_assisted', 'human_review_completed': False,
                  'gold_visible': False, 'max_attempts': 2, 'uncertain_request_retry': False}
    immutable(folder / 'provenance.json', provenance)
    client = CandidateProvider(settings, allow_live=True)
    client.offline = True
    labels, unresolved = [], []
    try:
        for index, row in enumerate(queue, 1):
            facts = [tool_fact(f) for fid in row['generated_artifact'].get('retrieved_fact_ids', []) if (f := repo.get(fid))]
            messages = review_messages(row, facts)
            key = digest([messages, provenance])
            record = {}
            for attempt in (1, 2):
                target = folder / f'{key}.{attempt}.json'
                intent = folder / f'{key}.{attempt}.request.json'
                if target.exists():
                    record = read_json(target)
                elif intent.exists():
                    record = {'error': 'Uncertain interrupted request; no resampling', 'retryable': False}
                else:
                    write_new_json(intent, {'messages': messages, 'timestamp': timestamp(),
                        'parameters': client.describe_request('judge', settings.model.base_seed)})
                    record = {'retryable': False}
                    try:
                        client.begin_question()
                        turn = client.complete(messages, [], role='judge', seed=settings.model.base_seed)
                        record.update(raw_response=asdict(turn), retryable=True)
                        if turn.tool_calls or turn.finish_reason != 'stop':
                            raise ValueError('Incomplete structured offline review')
                        record['verdict'] = parse_review(turn.content)
                    except Exception as exc:
                        record['error'] = f'{type(exc).__name__}: {exc}'
                    write_new_json(target, record)
                if 'verdict' in record or not record.get('retryable'):
                    break
            if 'verdict' in record:
                v = record['verdict']
                labels.append({'review_id': row['review_id'], 'artifact_hash': row['artifact_hash'],
                    'reviewer': f'{settings.model.judge_model} offline structured AI review',
                    'review_kind': 'ai_assisted', 'rationale': v['reason'], 'request_hash': key,
                    **{k: v[k] for k in REVIEW_FIELDS}})
            else:
                unresolved.append({'review_id': row['review_id'], 'error': record.get('error')})
            status('OFFLINE_REVIEW', processed=index, total=len(queue), unresolved=len(unresolved))
        client.verify_identity()
    finally:
        client.close()
    target = OUT / 'ai-review-labels.jsonl'
    if target.exists():
        if read_jsonl(target) != labels:
            raise ValueError('Offline label drift')
    else:
        write_new_jsonl(target, labels)
    immutable(folder / 'summary.json', {'labels': len(labels), 'unresolved': unresolved, 'queued': len(queue)})
    evaluate(OUT / 'evaluation-ai', target)


def main():
    global OUT
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--resume', action='store_true')
    profiles = parser.add_mutually_exclusive_group()
    profiles.add_argument('--candidate-v3', action='store_true')
    profiles.add_argument('--candidate-v4', action='store_true')
    args = parser.parse_args()
    config_path, OUT, study_stage = dev_profile(candidate_v3=args.candidate_v3, candidate_v4=args.candidate_v4)
    split = read_json(ROOT / 'artifacts/dataset_split.json')
    expected = schedule(split)
    settings = load_settings(config_path)
    if not (args.candidate_v3 or args.candidate_v4):
        original = read_json(ROOT / 'results/dev-ai-assisted-001/manifest.json')
        if original['project_hashes'] != project_hashes(ROOT) or original['settings'] != settings.model_dump():
            raise ValueError('Original controls changed')
    source = ROOT / 'data/financial_qa_gold_dataset_v2.xlsx'
    derived = ROOT / 'artifacts/derived' / file_hash(source)
    source_manifest = verify_derived(source, derived)
    prompts = generator_prompts(load_prompts(ROOT))
    prompts['judge'] = judge_prompt([{'role': 'system', 'content': prompts['judge']}])[0]['content']
    tracked = [Path(__file__), config_path, ROOT / 'scripts/dev_prompt_candidates.py', ROOT / 'scripts/pilot_dev_workflow.py',
               ROOT / 'scripts/probe_dev_judge.py', ROOT / 'scripts/complete_ai_study.py', ROOT / 'scripts/repair_offline_reviews.py',
               *sorted((ROOT / 'experiments/dev_prompt_v2').glob('*.md'))]
    manifest = {'schema_version': '1.0', 'experiment_id': OUT.name, 'experiment_kind': 'main',
        'study_stage': study_stage, 'mode': 'live', 'partition': 'development',
        'expected_runs': expected, 'settings': settings.model_dump(), 'source_manifest_hash': digest(source_manifest),
        'split_hash': digest(split), 'project_hashes': project_hashes(ROOT),
        'review_provenance': review_provenance(ROOT, settings, source_manifest), 'resolved_prompts': prompts,
        'candidate_hashes': {str(p.relative_to(ROOT)): file_hash(p) for p in tracked},
        'role_overrides': {'generator': 'prompt_only (unchanged)', 'online_judge_format': probe_schema(),
                           'offline_review_format': review_schema()},
        'candidate_controls': ({'repeat_penalty': 1.1, 'canonical_years': ('semantic_time_equivalence_v2' if args.candidate_v4 else 'roc_gregorian_equivalence_v1'),
                                'comparison_feedback': 'unified_comparison_repair_v1'}
                               if (args.candidate_v3 or args.candidate_v4) else None),
        'test_execution_allowed': False}
    if not args.live:
        print(json.dumps({'question_runs': len(expected), 'live_calls': 0, 'output': str(OUT)}))
        return
    settings.require_live()
    if OUT.exists() and not args.resume:
        raise FileExistsError('Output exists; explicit --resume required')
    if not OUT.exists() and args.resume:
        raise ValueError('Cannot resume absent experiment')
    OUT.mkdir(parents=True, exist_ok=True)
    immutable(OUT / 'manifest.json', manifest)
    status('PREFLIGHT', total=144)
    client = CandidateProvider(settings, allow_live=True)
    try:
        immutable(OUT / 'runtime.json', {'runtime': client.runtime, 'hardware': environment_snapshot()})
        inputs = {q['question_id']: q for q in read_jsonl(derived / 'question_inputs.jsonl')}
        public_ids = {q['question_id']: q['public_question_id'] for q in read_jsonl(derived / 'question_metadata.jsonl')}
        repo = FactRepository(derived / 'financial_facts.sqlite', yaml.safe_load((ROOT / 'config/concept_aliases.yaml').read_text(encoding='utf-8')), settings.search_top_k)
        client.calls = sum(e['event'] in ('generator_request', 'judge_request') for p in OUT.glob('run_*/[ABCD]/events.jsonl') for e in read_jsonl(p))
        for run in (1, 2, 3):
            for condition in 'ABCD':
                with TraceStore(OUT / f'run_{run:02d}' / condition) as store:
                    runner = AnnotationRunner(settings, repo, load_rules(ROOT), prompts, client, store,
                        trace_context={'study_stage': study_stage, 'candidate_hash': digest(manifest['candidate_hashes'])})
                    for item in [x for x in expected if x['run_index'] == run and x['condition'] == condition]:
                        qid = item['question_id']
                        raw = inputs[public_ids[qid]]
                        question = QuestionInput(question_id=raw['question_id'], question=raw[settings.language], language=settings.language)
                        status('GENERATION', current=item, completed=sum(len(read_jsonl(p)) for p in OUT.glob('run_*/[ABCD]/finals.jsonl')), total=144)
                        runner.run_question(question, source_question_id=qid, condition=condition, run_index=run, experiment_id=OUT.name)
                        recent = [a for a in store.read('attempts') if a['question_id'] == qid]
                        if any(a.get('runtime_error_type') in {'CONNECTION_ERROR', 'MODEL_NOT_FOUND', 'CALL_BUDGET'} for a in recent):
                            raise RuntimeError('Infrastructure failure; stop remaining inference')
        client.verify_identity()
    finally:
        client.close()
    finals = [r for p in OUT.glob('run_*/[ABCD]/finals.jsonl') for r in read_jsonl(p)]
    actual = {(r['run_index'], r['condition'], r['question_id']) for r in finals}
    if len(finals) != 144 or actual != {(x['run_index'], x['condition'], x['question_id']) for x in expected}:
        raise ValueError('Incomplete or duplicate Development results')
    status('GENERATION_COMPLETE', completed=144, total=144)
    offline_review(settings, repo)
    metrics = read_json(OUT / 'evaluation-ai/aggregate_metrics.json')
    if project_hashes(ROOT) != manifest['project_hashes'] or file_hash(source) != split['source_sha256']:
        raise ValueError('Core or source changed during execution')
    status('COMPLETE' if metrics['pending_review_count'] == 0 else 'COMPLETE_WITH_UNRESOLVED_REVIEWS',
           completed=144, total=144, pending_reviews=metrics['pending_review_count'])


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        if OUT is not None and OUT.exists() and (OUT / 'manifest.json').exists():
            status('STOPPED_WITH_ERROR', error=f'{type(exc).__name__}: {exc}')
            (OUT / 'error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        raise
