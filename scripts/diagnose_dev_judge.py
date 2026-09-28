"""Dev-only paired Judge diagnostic. No Generator, Test, Gold labels or core edits."""
import argparse
import copy
import csv
from dataclasses import asdict
import html
import json
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from financial_annotation_harness.config import load_settings, load_rules
from financial_annotation_harness.facts import FactRepository, tool_fact
from financial_annotation_harness.governance import project_hashes
from financial_annotation_harness.io_utils import read_json, read_jsonl, file_hash, digest, canonical, write_new_json, write_new_jsonl, timestamp
from financial_annotation_harness.judge import parse_judge
from financial_annotation_harness.ollama_provider import OllamaProvider
from financial_annotation_harness.python_executor import execute_python
from financial_annotation_harness.validators import ValidationContext, validate_all, all_pass
from probe_dev_judge import probe_schema

BASE = ROOT / 'outputs/dev-prompt-v4/full-dev-v4'
DEFAULT_OUT = ROOT / 'outputs/dev-judge-diagnostic-v1'


def fraction(n, d):
    return {'numerator': n, 'denominator': d, 'rate': n / d if d else None}


def metrics(rows):
    bad = [r for r in rows if not r['expected_pass'] and r['deterministic_pass']]
    good = [r for r in rows if r['expected_pass']]
    rejected = lambda r: r.get('verdict', {}).get('overall_pass') is False
    return {'cases': len(rows), 'errors': sum('verdict' not in r for r in rows),
            'incremental_detection': fraction(sum(map(rejected, bad)), len(bad)),
            'false_rejection': fraction(sum(map(rejected, good)), len(good)),
            'correct_acceptance': fraction(sum(r.get('verdict', {}).get('overall_pass') is True for r in good), len(good)),
            'blocked_errors': sum(not r['expected_pass'] and not r['deterministic_pass'] for r in rows),
            'mean_latency_ms': sum(r['latency_ms'] for r in rows) / len(rows) if rows else None}


def blind_messages(system, row):
    payload = row['payload']
    assert set(payload) == {'original_question', 'generated_structured_artifact', 'candidate_financial_facts', 'selected_financial_facts'}
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': canonical(payload)}]


def request_state(folder, key):
    target = folder / (key + '.json')
    if target.exists():
        return read_json(target)
    if (folder / (key + '.request.json')).exists():
        raise RuntimeError('Uncertain interrupted request; no automatic resampling: ' + key)
    return None


def immutable(path, value):
    if path.exists():
        assert read_json(path) == value, 'Provenance drift: ' + str(path)
    else:
        write_new_json(path, value)


def build_cases(repo, rules):
    events = read_jsonl(BASE / 'run_01/D/events.jsonl')
    originals = {}
    systems = set()
    for e in events:
        if e.get('event') == 'judge_request':
            systems.add(e['messages'][0]['content'])
            originals.setdefault(e['question_id'], json.loads(e['messages'][1]['content']))
    split = read_json(ROOT / 'artifacts/dataset_split.json')
    assert set(originals) == set(split['development']) and len(originals) == 12
    assert len(systems) == 1
    cases = []
    def add(qid, category, payload, reason, target):
        cases.append({'case_id': qid + '__' + category, 'source_question_id': qid,
                      'category': category, 'expected_pass': category == 'control',
                      'label_authority': 'AI-authored diagnostic hypothesis; not human adjudication',
                      'expected_criterion': target, 'reason': reason, 'payload': payload})
    for qid, payload in sorted(originals.items()):
        add(qid, 'control', copy.deepcopy(payload), '原始 Dev 最終標註，沿用已完成的 AI 內容與獨立公式檢查；非人工真值。', 'overall_pass')
    for qid in ('SF06', 'SF09', 'RT04'):
        p = copy.deepcopy(originals[qid])
        p['generated_structured_artifact']['semantic_parse']['concept'] = ['存貨']
        add(qid, 'wrong_concept', p, '題目未問存貨，但 semantic_parse.concept 改為存貨；其餘保留。', 'semantic_parse_pass')
    for qid in ('CP03', 'CP05', 'LG03'):
        p = copy.deepcopy(originals[qid]); a = p['generated_structured_artifact']
        if qid.startswith('CP'):
            a['semantic_parse']['logic'] = '比較各年數值並選擇最低的一年'
            a['python_solution'] = a['python_solution'].replace('max(', 'min(')
            a['python_solution'] = '\n'.join(line for line in a['python_solution'].splitlines() if not line.lstrip().startswith('#'))
            reason = '原題要求最高，改為選擇最低；Python 與答案一起改，保留內部一致性。'
        else:
            a['semantic_parse']['logic'] = '只要任一相鄰年度淨利下降就回答 Yes'
            a['python_solution'] = a['python_solution'].replace(' and ', ' or ')
            a['python_solution'] = '\n'.join(line for line in a['python_solution'].splitlines() if not line.lstrip().startswith('#'))
            reason = '原題要求逐年下降，改成任一相鄰年下降；本題答案碰巧不變，但量詞與運算已錯。'
        execution = execute_python(a['python_solution'], **rules['execution'])
        assert execution['success'], execution
        a['answer'] = execution['result']
        add(qid, 'wrong_constraint', p, reason, 'semantic_parse_pass')
    for qid, concept in [('SF06', 'operating_revenue'), ('SF09', 'net_profit'), ('GR03', 'total_liabilities')]:
        p = copy.deepcopy(originals[qid]); a = p['generated_structured_artifact']
        years = sorted({f['year'] for f in p['selected_financial_facts']})
        search = repo.search_financial_facts(concept, years=years, top_k=12)
        fs = [f for f in search['candidates'] if f['concept_id'] == concept]
        assert len(fs) == len(years)
        fs = sorted(fs, key=lambda f: f['year'])
        a['selected_evidence'] = [{'fact_id': f['fact_id'], 'value': f['value'], 'unit': f['unit'], 'variable_name': 'value_' + str(f['year']), 'index_key': None} for f in fs]
        a['retrieved_fact_ids'] = [f['fact_id'] for f in fs]
        a['semantic_parse']['concept'] = [fs[0]['concept']]
        a['golden_context'] = '| 項目 | ' + ' | '.join(str(y) for y in years) + ' |\n| --- | ' + ' | '.join('---' for _ in years) + ' |\n| ' + fs[0]['concept'] + ' | ' + ' | '.join(f['value'] for f in fs) + ' |\n來源單位：TWD_thousand'
        code = 'def solution():\n' + ''.join(f"    value_{f['year']} = {f['value']}\n" for f in fs)
        code += (f'    return value_{years[0]}' if len(fs) == 1 else f'    return round((value_{years[1]} - value_{years[0]}) / value_{years[0]} * 100, 2)')
        a['python_solution'] = code
        ex = execute_python(code, **rules['execution']); assert ex['success']
        a['answer'] = ex['result']
        # Actual deterministic search, synthetic selection. Never claim these were original Generator calls.
        pool = {f['fact_id']: f for f in p['candidate_financial_facts'] + fs}
        p['candidate_financial_facts'] = list(pool.values())
        p['selected_financial_facts'] = fs
        add(qid, 'wrong_evidence', p, '以同年、同單位但不同概念的真實 facts 取代所問概念，同步修改 Context、綁定、Python 與答案。', 'concept_pass')
        cases[-1]['synthetic_search_result'] = search
    for qid in ('AR07', 'AR09', 'RT07'):
        p = copy.deepcopy(originals[qid])
        p['generated_structured_artifact']['golden_context'] = 'No financial facts are provided in this context.'
        add(qid, 'missing_context', p, '移除 Context 表格；candidate facts 仍存在，不能彌補 Context 不足。', 'golden_context_pass')
    for row in cases:
        p = row['payload']; a = p['generated_structured_artifact']
        c = ValidationContext(a['question_id'], p['original_question'], repo, rules,
                              retrieved_ids={f['fact_id'] for f in p['candidate_financial_facts']})
        _, results = validate_all(a, c)
        row['deterministic_pass'] = all_pass(results)
        row['validation_results'] = [r.model_dump(mode='json') for r in results]
        row['question_type'] = a['question_type']
        row['payload_hash'] = digest(p)
        if row['expected_pass']:
            assert row['deterministic_pass'], row['case_id']
    random.Random(20260917).shuffle(cases)
    assert len(cases) == 24
    return systems.pop(), cases


class DiagnosticProvider(OllamaProvider):
    def describe_request(self, role, seed):
        p = super().describe_request(role, seed)
        p['format'] = probe_schema()
        return p


def render(out, cases, models):
    rows = []
    for name in models:
        for case in cases:
            path = out / name / (case['case_id'] + '.json')
            if path.exists():
                rows.append({**{k: case[k] for k in ('case_id', 'category', 'source_question_id', 'question_type', 'expected_pass', 'expected_criterion', 'deterministic_pass')}, 'model': name, **read_json(path)})
    summary = {'scope': 'Synthetic Dev Judge diagnostic, not A/B/C/D accuracy or held-out performance',
               'expected_requests': len(cases) * len(models), 'completed_requests': len(rows),
               'human_review_completed': False, 'by_model': {m: metrics([r for r in rows if r['model'] == m]) for m in models},
               'by_category': {m: {c: metrics([r for r in rows if r['model'] == m and r['category'] == c]) for c in sorted({r['category'] for r in cases})} for m in models}}
    write_new_json(out / 'summary.json', summary)
    write_new_jsonl(out / 'results.jsonl', rows)
    with (out / 'results.csv').open('x', encoding='utf-8-sig', newline='') as f:
        fields = ['model','case_id','question_type','category','expected_pass','deterministic_pass','observed_pass','criterion_pass','latency_ms','error','feedback']
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader()
        for r in rows:
            v = r.get('verdict', {})
            writer.writerow({**{k: r.get(k) for k in fields[:6]}, 'observed_pass': v.get('overall_pass'), 'criterion_pass': v.get(r['expected_criterion']), 'latency_ms': r['latency_ms'], 'error': r.get('error'), 'feedback': v.get('feedback')})
    def pct(v):
        return f"{v['numerator']}/{v['denominator']}（{v['rate']:.1%}）" if v['rate'] is not None else '不適用'
    table = ''.join('<tr><th>'+html.escape(m)+'</th><td>'+pct(v['incremental_detection'])+'</td><td>'+pct(v['false_rejection'])+'</td><td>'+pct(v['correct_acceptance'])+f"</td><td>{v['errors']}</td><td>{v['mean_latency_ms']/1000:.2f} 秒</td></tr>" for m,v in summary['by_model'].items())
    details = []
    lookup = {c['case_id']: c for c in cases}
    for r in rows:
        c = lookup[r['case_id']]; v = r.get('verdict', {})
        label = '推論／解析失敗' if not v else ('接受' if v['overall_pass'] else '拒絕')
        details.append('<details data-category="'+r['category']+'"><summary>'+html.escape(r['model']+' / '+r['case_id']+' / '+label)+(' / 通過 C' if r['deterministic_pass'] else ' / C 已攔截')+'</summary><p>'+html.escape(c['reason'])+'</p><p><b>Judge 回饋：</b>'+html.escape(v.get('feedback',r.get('error','')) )+'</p><pre>'+html.escape(json.dumps({'question':c['payload']['original_question'], 'artifact':c['payload']['generated_structured_artifact'], 'judge':v, 'deterministic_failures':[i for x in c['validation_results'] for i in x['issues']]},ensure_ascii=False,indent=2))+'</pre></details>')
    page = '''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>Judge 診斷實驗</title><style>body{font:16px/1.7 Microsoft JhengHei,sans-serif;max-width:1200px;margin:30px auto;padding:20px;background:#f4f7fb;color:#18324b}table{border-collapse:collapse;width:100%;background:white}td,th{border:1px solid #ccd;padding:10px}details{background:white;padding:14px;margin:10px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}select{font:inherit;padding:8px}</style><h1>Judge 是否能攔截程式規則漏掉的錯誤？</h1><p>12 個 Dev 原始案例＋12 個 AI 設計的合成錯誤案例，每模型各 24 次 fresh-context request。不是正式 A/B/C/D 成績；正確性標籤由 AI 檢查與明確變異規則建立，未經人工獨立審查。兩模型皆沿用 v4 D 組 rubric，不使用 Gold Answer。</p><table><tr><th>模型</th><th>C 通過錯誤的攔截率</th><th>正確案例誤拒率</th><th>正確案例接受率</th><th>請求／解析錯誤</th><th>平均耗時</th></tr>'''+table+'''</table><p>攔截率分母包含所有通過 C 的錯誤案例；timeout 與格式錯誤不算成功攔截。Context 缺失若已被 C 擋下，只列診斷結果，不計 Judge 增量。平均耗時包含模型載入與請求成本；單次、固定模型順序，不能作嚴格速度排名。兩個模型的 template 與未明示的原生預設仍可能不同。</p><p>同一題衍生的案例不是獨立樣本；已知 Dev 與合成缺陷僅能定位弱點，不能推估真實錯誤盛行率或證明 D 必定優於 C。</p><h2>逐筆結果與可檢查的輸入</h2><select onchange="document.querySelectorAll('details').forEach(e=>e.hidden=this.value!=='all'&&e.dataset.category!==this.value)"><option value="all">全部</option>'''+''.join('<option>'+c+'</option>' for c in sorted({c['category'] for c in cases}))+ '</select>'+''.join(details)+'</html>'
    (out / 'report.html').write_text(page, encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--configs', nargs=2, type=Path, default=[ROOT/'config/experiment.dev-candidate-v3.json', ROOT/'config/experiment.qwen35-9b.probe.json'])
    args = parser.parse_args(); out = args.output
    source = ROOT / 'data/financial_qa_gold_dataset_v2.xlsx'
    source_hash = file_hash(source)
    repo = FactRepository(ROOT / 'artifacts/derived' / source_hash / 'financial_facts.sqlite')
    rules = load_rules(ROOT)
    system, cases = build_cases(repo, rules)
    inputs = {str(p.relative_to(ROOT)):file_hash(p) for p in BASE.rglob('*') if p.is_file()}
    configs = {}
    for i, path in enumerate(args.configs, 1):
        settings = load_settings(path)
        # This diagnostic fixes shared explicit parameters; original config stays unchanged.
        settings.model.repeat_penalty = 1.1
        settings.max_live_calls = len(cases)
        configs[f'model_{i}'] = settings
    manifest = {'kind':'dev_synthetic_judge_diagnostic','source_sha256':source_hash,'project_hashes':project_hashes(ROOT),
                'source_file_hashes':inputs,'script_hash':file_hash(Path(__file__)), 'system':system,'schema':probe_schema(),
                'settings':{k:v.model_dump() for k,v in configs.items()},'case_hash':digest(cases),'request_order_seed':20260917,
                'policy':'one fresh request per case/model; no repair/retry; errors stay in denominators; no Gold labels sent',
                'config_hashes':{str(p):file_hash(p) for p in args.configs},'test_execution_allowed':False}
    out.mkdir(parents=True,exist_ok=True)
    immutable(out/'manifest.json',manifest)
    if (out/'cases.jsonl').exists(): assert read_jsonl(out/'cases.jsonl') == cases
    else: write_new_jsonl(out/'cases.jsonl',cases)
    print(json.dumps({'prepared_cases':len(cases),'correct':sum(c['expected_pass'] for c in cases),'eligible_errors':sum(not c['expected_pass'] and c['deterministic_pass'] for c in cases),'blocked_errors':sum(not c['expected_pass'] and not c['deterministic_pass'] for c in cases),'live':args.live}),flush=True)
    if not args.live: return
    for name, settings in configs.items():
        folder=out/name; folder.mkdir(exist_ok=True)
        client=DiagnosticProvider(settings,allow_live=True)
        try:
            immutable(folder/'runtime.json',client.runtime)
            for i,case in enumerate(cases,1):
                key=case['case_id']; record=request_state(folder,key)
                messages=blind_messages(system,case)
                if record is None:
                    write_new_json(folder/(key+'.request.json'),{'messages':messages,'parameters':client.describe_request('judge',settings.model.base_seed),'timestamp':timestamp()})
                    record={}; started=time.monotonic()
                    try:
                        client.begin_question()
                        turn=client.complete(messages,[],role='judge',seed=settings.model.base_seed)
                        record['raw_response']=asdict(turn)
                        if turn.finish_reason!='stop' or turn.tool_calls: raise ValueError('Incomplete Judge response')
                        record['verdict']=parse_judge(turn.content).model_dump(mode='json')
                    except Exception as exc:
                        record['error']=f'{type(exc).__name__}: {exc}'
                    record['latency_ms']=round((time.monotonic()-started)*1000)
                    write_new_json(folder/(key+'.json'),record)
                print(json.dumps({'model':name,'completed':i,'total':len(cases),'case':key,'error':record.get('error')}),flush=True)
            client.verify_identity()
        finally:
            client.unload()
            client.close()
    assert file_hash(source)==source_hash
    assert project_hashes(ROOT)==manifest['project_hashes']
    assert all(file_hash(ROOT/p)==h for p,h in inputs.items()),'Existing results changed'
    if not (out/'summary.json').exists():
        summary=render(out,cases,configs)
        print(json.dumps(summary,ensure_ascii=False),flush=True)
    immutable(out/'verification.json',{'source_unchanged':True,'old_results_unchanged':True,'core_unchanged':True,'completed_requests':48})

if __name__=='__main__': main()
