"""Five Dev-only component probes; no Generator run or Test tuning."""
import copy
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from financial_annotation_harness.config import load_settings
from financial_annotation_harness.io_utils import read_jsonl, read_json, write_new_json, file_hash
from financial_annotation_harness.judge import parse_judge
from financial_annotation_harness.ollama_provider import OllamaProvider
from financial_annotation_harness.schemas import JudgeResult
import httpx

CHECKLIST = '''逐欄核對 original_question 與 generated_structured_artifact.semantic_parse 的 time、concept、filter、logic。
即使 evidence 或 answer 正確，只要 semantic_parse 改變公司、目標概念、運算或量詞，semantic_parse_pass 必須為 false。
公司同義名稱依可見資料合理辨識；不要自行捏造公司譯名或把縮寫當作不同公司。
Golden Context 必須自行包含必要財務 facts；外部 candidates 有資料不能彌補空白 Context。
每項失敗的 feedback 應定位真正有錯的欄位，說明原題要求與輸出差異，給出可執行修正。
只用 SEMANTIC_PARSE_ERROR、CONCEPT_ERROR、EVIDENCE_ERROR、UNSUPPORTED_ANSWER；Context 不足用 EVIDENCE_ERROR。
不要新增 GOLDEN_CONTEXT_ERROR 或其他錯誤碼。這些是四項既有 rubric 的操作說明，不增加評估標準。'''


def probe_schema():
    schema = JudgeResult.model_json_schema()
    schema['$defs']['FailureCode']['enum'] = ['SEMANTIC_PARSE_ERROR', 'CONCEPT_ERROR', 'EVIDENCE_ERROR', 'UNSUPPORTED_ANSWER']
    return schema


class ProbeHTTP:
    def __init__(self, base_url):
        self.client = httpx.Client(base_url=base_url, trust_env=False)

    def request(self, method, path, **kwargs):
        if path == '/api/chat':
            kwargs['json'] = {**kwargs['json'], 'format': probe_schema()}
        return self.client.request(method, path, **kwargs)

    def close(self):
        self.client.close()


def cases(extended=False):
    events = read_jsonl(ROOT / 'results/dev-ai-assisted-001/run_01/D/events.jsonl')
    messages = next(e['messages'] for e in events if e.get('event') == 'judge_request' and e['question_id'] == 'SF06')
    original = json.loads(messages[1]['content'])
    items = [('original', original, 'overall_pass', True)]
    for name, field, value, criterion in [
        ('wrong_concept', 'concept', ['營業收入'], 'semantic_parse_pass'),
        ('wrong_entity', 'filter', ['台積電'], 'semantic_parse_pass'),
        ('wrong_logic', 'logic', 'Compute year-over-year growth instead of reporting the requested amount', 'semantic_parse_pass'),
    ]:
        payload = copy.deepcopy(original)
        payload['generated_structured_artifact']['semantic_parse'][field] = value
        items.append((name, payload, criterion, False))
    payload = copy.deepcopy(original)
    payload['generated_structured_artifact']['golden_context'] = 'No financial facts are provided in this context.'
    items.append(('missing_context', payload, 'golden_context_pass', False))
    result = [(name, [messages[0], {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}], criterion, expected)
              for name, payload, criterion, expected in items]
    if extended:
        extra = next(e['messages'] for e in events if e.get('event') == 'judge_request' and e['question_id'] == 'AR09')
        result.append(('ar09_original', copy.deepcopy(extra), 'overall_pass', True))
        for name, field, value in [('ar09_wrong_entity', 'filter', ['台積電']), ('ar09_wrong_concept', 'concept', ['存貨'])]:
            payload = json.loads(extra[1]['content'])
            payload['generated_structured_artifact']['semantic_parse'][field] = value
            result.append((name, [extra[0], {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}], 'semantic_parse_pass', False))
    return result


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--candidate', action='store_true')
    group.add_argument('--prompt-v2', action='store_true')
    parser.add_argument('--extended', action='store_true')
    args = parser.parse_args()
    dest = ROOT / 'outputs/offline-repair-v1' / ('dev-judge-candidate' if args.candidate else 'dev-judge-probes')
    if args.prompt_v2:
        dest = ROOT / 'outputs/dev-prompt-v2/judge'
    if args.extended:
        dest = dest.with_name(dest.name + '-extended')
    dest.mkdir(parents=True, exist_ok=True)
    settings = load_settings(ROOT / 'config/experiment.ai-assisted.v1.json')
    constrained = args.candidate or args.prompt_v2
    client = OllamaProvider(settings, allow_live=True, http_client=ProbeHTTP(settings.model.base_url) if constrained else None)
    summaries = []
    try:
        for name, messages, criterion, expected in cases(args.extended):
            messages = copy.deepcopy(messages)
            if args.prompt_v2:
                from dev_prompt_candidates import judge_prompt
                messages = judge_prompt(messages)
            elif args.candidate:
                messages[0]['content'] += '\n' + CHECKLIST
            record_path = dest / f'{name}.json'
            intent = dest / f'{name}.request.json'
            if record_path.exists():
                if read_json(intent)['messages'] != messages:
                    raise ValueError('Probe prompt drift; use a new versioned output')
                record = read_json(record_path)
            else:
                if intent.exists():
                    raise RuntimeError('Interrupted probe; no automatic resampling')
                write_new_json(intent, {'messages': messages, 'expected_criterion': criterion, 'expected_value': expected,
                                       'parameters': client.describe_request('judge', settings.model.base_seed),
                                       'script_hash': file_hash(Path(__file__)), 'synthetic_dev_probe': True,
                                       'candidate': args.candidate,
                                       'prompt_v2': args.prompt_v2,
                                       'format': probe_schema() if constrained else None})
                record = {}
                try:
                    client.begin_question()
                    turn = client.complete(messages, [], role='judge', seed=settings.model.base_seed)
                    record['raw_response'] = asdict(turn)
                    if turn.finish_reason != 'stop' or turn.tool_calls:
                        raise ValueError('Incomplete judge response')
                    record['verdict'] = parse_judge(turn.content).model_dump(mode='json')
                except Exception as exc:
                    record['error'] = f'{type(exc).__name__}: {exc}'
                write_new_json(record_path, record)
            summaries.append({'case': name, 'criterion': criterion, 'expected': expected,
                              'observed': record.get('verdict', {}).get(criterion),
                              'correct': record.get('verdict', {}).get(criterion) is expected,
                              'error': record.get('error')})
            print(json.dumps(summaries[-1]), flush=True)
    finally:
        client.close()
    if not (dest / 'summary.json').exists():
        write_new_json(dest / 'summary.json', {'scope': 'Dev synthetic component probe; not main experimental accuracy', 'cases': summaries})


if __name__ == '__main__':
    main()
