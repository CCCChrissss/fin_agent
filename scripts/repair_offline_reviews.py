"""Versioned offline measurement repair; never runs a Generator or edits v1 records."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from complete_ai_study import parse_review, REVIEW_FIELDS, RUBRIC
from financial_annotation_harness.config import load_settings
from financial_annotation_harness.governance import project_hashes
from financial_annotation_harness.io_utils import read_json, read_jsonl, write_new_json, write_new_jsonl, digest, file_hash, timestamp
from financial_annotation_harness.ollama_provider import OllamaProvider, local_url
import httpx


def review_schema():
    return {'type': 'object', 'additionalProperties': False,
            'properties': {**{k: {'type': 'boolean'} for k in REVIEW_FIELDS},
                           'reason': {'type': 'string', 'minLength': 1}},
            'required': [*REVIEW_FIELDS, 'reason']}


class StructuredHTTP:
    """Adds the measurement-only schema at the HTTP boundary, preserving core provider."""
    def __init__(self, base_url):
        self.client = httpx.Client(base_url=local_url(base_url), trust_env=False)
        self.last_payload = None

    def request(self, method, path, **kwargs):
        if path == '/api/chat':
            kwargs['json'] = {**kwargs['json'], 'format': review_schema()}
            self.last_payload = kwargs['json']
        return self.client.request(method, path, **kwargs)

    def close(self):
        self.client.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--partition', choices=['dev', 'test'], required=True)
    parser.add_argument('--limit', type=int, default=0, help='Maximum unique artifacts; zero means all')
    args = parser.parse_args()
    folder = ROOT / 'results' / f'{args.partition}-ai-assisted-001'
    dest = ROOT / 'outputs' / 'offline-repair-v1' / args.partition
    manifest = read_json(folder / 'manifest.json')
    if manifest['project_hashes'] != project_hashes(ROOT):
        raise ValueError('Frozen core code/rules changed; stop before measurement')
    if args.partition == 'test':
        dev = read_json(dest.parent / 'dev' / 'summary.json')
        if dev['unresolved'] or dev['remaining_unique']:
            raise ValueError('Complete and validate Dev repair before Test measurement')
    records = []
    for path in sorted((folder / 'offline-ai-review').glob('*.json')):
        if path.name.endswith('.request.json') or path.name in ('summary.json', 'provenance.json'):
            continue
        record = read_json(path)
        if 'verdict' not in record:
            records.append(path)
    settings = load_settings(ROOT / 'config/experiment.ai-assisted.v1.json')
    provenance = {'version': 'offline-format-repair-v1', 'script_hash': file_hash(Path(__file__)),
                  'original_manifest_hash': file_hash(folder / 'manifest.json'),
                  'original_summary_hash': file_hash(folder / 'offline-ai-review/summary.json'),
                  'rubric_hash': digest(RUBRIC), 'schema': review_schema(),
                  'model': settings.model.model_dump(), 'max_attempts_per_unique_artifact': 2,
                  'semantic_rubric_changed': False, 'human_review_completed': False,
                  'policy': 'Keep valid v1 labels. Rejudge invalid outputs in fresh context. Never retry uncertain transport failures.'}
    dest.mkdir(parents=True, exist_ok=True)
    pp = dest / 'provenance.json'
    if pp.exists():
        if read_json(pp) != provenance:
            raise ValueError('Repair provenance drift')
    else:
        write_new_json(pp, provenance)
    http = StructuredHTTP(settings.model.base_url)
    client = OllamaProvider(settings, allow_live=True, http_client=http)
    verdicts, unresolved, processed = {}, [], 0
    try:
        for path in records:
            key = path.stem
            request = read_json(path.with_name(key + '.request.json'))
            messages = request['messages']
            if len(messages) != 2 or messages[0]['content'] != RUBRIC:
                raise ValueError('Unexpected original review context')
            visible = json.loads(messages[1]['content'])
            if set(visible) != {'original_question', 'generated_annotation', 'financial_facts'}:
                raise ValueError('Unexpected review payload fields')
            verdict = None
            for attempt in (1, 2):
                rp = dest / f'{key}.{attempt}.json'
                ip = dest / f'{key}.{attempt}.request.json'
                if rp.exists():
                    response = read_json(rp)
                elif ip.exists():
                    response = {'error': 'Uncertain interrupted request; no automatic resampling', 'retryable': False}
                else:
                    write_new_json(ip, {'messages': messages,
                        'parameters': {**client.describe_request('judge', settings.model.base_seed), 'format': review_schema()},
                        'original_request_hash': file_hash(path.with_name(key + '.request.json')),
                        'timestamp': timestamp()})
                    response = {'original_record_hash': file_hash(path), 'attempt': attempt}
                    try:
                        client.begin_question()
                        turn = client.complete(messages, [], role='judge', seed=settings.model.base_seed)
                        response['raw_response'] = asdict(turn)
                        response['wire_payload'] = http.last_payload
                        response['retryable'] = True
                        if turn.finish_reason != 'stop' or turn.tool_calls:
                            raise ValueError('Incomplete structured review')
                        response['verdict'] = parse_review(turn.content)
                    except Exception as exc:
                        response['error'] = f'{type(exc).__name__}: {exc}'
                        response.setdefault('retryable', False)
                    write_new_json(rp, response)
                if 'verdict' in response:
                    verdict = response['verdict']
                    break
                if not response.get('retryable'):
                    break
            if verdict:
                verdicts[key] = verdict
            else:
                unresolved.append({'cache_key': key, 'error': response.get('error')})
            processed += 1
            print(json.dumps({'partition': args.partition, 'unique_processed': processed, 'unique_total': len(records),
                              'resolved': len(verdicts), 'unresolved': len(unresolved)}), flush=True)
            if args.limit and processed >= args.limit:
                break
    finally:
        client.close()
    labels = read_jsonl(folder / 'ai-review-labels.jsonl')
    old_provenance = read_json(folder / 'offline-ai-review/provenance.json')
    by_key = {digest([read_json(p.with_name(p.stem + '.request.json'))['messages'], old_provenance]): p.stem for p in records}
    from complete_ai_study import review_messages
    from financial_annotation_harness.facts import FactRepository, tool_fact
    source = ROOT / 'data/financial_qa_gold_dataset_v2.xlsx'
    repo = FactRepository(ROOT / 'artifacts/derived' / file_hash(source) / 'financial_facts.sqlite')
    for row in read_jsonl(folder / 'evaluation-mechanical/review_queue.jsonl'):
        facts = [tool_fact(f) for fid in row['generated_artifact'].get('retrieved_fact_ids', []) if (f := repo.get(fid))]
        key = by_key.get(digest([review_messages(row, facts), old_provenance]))
        if key in verdicts:
            v = verdicts[key]
            labels.append({'review_id': row['review_id'], 'artifact_hash': row['artifact_hash'],
                           'reviewer': f'{settings.model.judge_model} structured offline repair v1',
                           'review_kind': 'ai_assisted', 'rationale': v['reason'], 'request_hash': key,
                           **{k: v[k] for k in REVIEW_FIELDS}})
    summary = {'partition': args.partition, 'unique_total': len(records), 'unique_processed': processed,
               'remaining_unique': len(records) - processed, 'resolved_unique': len(verdicts),
               'unresolved': unresolved, 'labels': len(labels)}
    if args.limit:
        print(json.dumps(summary), flush=True)
        return
    if not (dest / 'summary.json').exists():
        write_new_json(dest / 'summary.json', summary)
        write_new_jsonl(dest / 'labels.jsonl', labels)
    output = dest / 'evaluation'
    if not output.exists():
        subprocess.run([sys.executable, '-B', '-m', 'financial_annotation_harness', 'evaluate',
                        '--experiment', str(folder), '--reviews', str(dest / 'labels.jsonl'), '--output', str(output)],
                       cwd=ROOT, env={**os.environ, 'PYTHONPATH': str(ROOT / 'src'), 'PYTHONIOENCODING': 'utf-8'}, check=True)


if __name__ == '__main__':
    main()
