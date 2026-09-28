"""Offline replay of five existing Dev artifacts; no model calls or score replacement."""
import json
import html
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from financial_annotation_harness.io_utils import read_jsonl, read_json, file_hash, write_new_json
from financial_annotation_harness.governance import project_hashes
from financial_annotation_harness.config import load_rules
from financial_annotation_harness.facts import FactRepository
from financial_annotation_harness.validators import ValidationContext, validate_all

def main():
    source = ROOT / 'data/financial_qa_gold_dataset_v2.xlsx'
    source_hash = file_hash(source)
    split = read_json(ROOT / 'artifacts/dataset_split.json')
    assert source_hash == split['source_sha256']
    base = ROOT / 'outputs/dev-prompt-v2/full-dev'
    derived = ROOT / 'artifacts/derived' / source_hash
    repo = FactRepository(derived / 'financial_facts.sqlite')
    inputs = {r['question_id']: r for r in read_jsonl(derived / 'question_inputs.jsonl')}
    ids = {'CP03', 'GR03', 'LG01', 'LG03', 'RT04'}
    assert ids <= set(split['development'])
    rows = []
    for final in read_jsonl(base / 'run_01/D/finals.jsonl'):
        if final['question_id'] not in ids:
            continue
        raw = final['artifact']
        if raw is None:
            rows.append({'question_id': final['question_id'], 'status': 'UNRESOLVED_PROVIDER_FAILURE',
                         'note': 'Original failed wire response was not recorded. Offline replay cannot recover it.'})
            continue
        context = ValidationContext(raw['question_id'], inputs[raw['question_id']]['zh'], repo, load_rules(ROOT), set(raw['retrieved_fact_ids']))
        _, checks = validate_all(raw, context)
        rows.append({'question_id': final['question_id'], 'issues': [i.model_dump(mode='json') for v in checks for i in v.issues]})
    by_id = {r['question_id']: r for r in rows}
    assert any(i['rule_id'] == 'TYPE-03' for i in by_id['CP03']['issues'])
    assert any('Missing years: [2025]' in i['recommended_correction'] for i in by_id['GR03']['issues'])
    assert any('statement if/else' in str(i['observed_value']) for i in by_id['LG03']['issues'])
    assert any('Missing source rows' in str(i['observed_value']) for i in by_id['RT04']['issues'])
    output = ROOT / 'outputs/engineering-repair-v1'
    output.mkdir(exist_ok=False)
    report = {'scope': 'Offline diagnostic replay, not new model results or replacement scores',
              'source_hash': source_hash, 'core_hashes': project_hashes(ROOT),
              'original_manifest_hash': file_hash(base / 'manifest.json'), 'rows': rows, 'live_calls': 0}
    write_new_json(output / 'verification.json', report)
    sections = ''.join('<h2>'+r['question_id']+'</h2><pre>'+html.escape(json.dumps(r, ensure_ascii=False, indent=2))+'</pre>' for r in rows)
    (output / 'report.html').write_text('<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>工程修正離線驗證</title><style>body{font:16px/1.7 sans-serif;margin:36px;max-width:1100px}pre{white-space:pre-wrap;background:#eef3f8;padding:18px}</style><h1>工程修正：五題 Dev 離線驗證</h1><p>使用原始模型輸出檢查新版錯誤回饋。模型呼叫 0 次；不修改舊分數、Gold 或原始 trace。LG01 的舊失敗回應無法回溯，需新的一次有限診斷。其餘四題已通過預期錯誤定位斷言。新版尚未 Freeze，舊 freeze 與 runner 的版本不一致保護應繼續生效。</p>'+sections+'</html>', encoding='utf-8')
    print(json.dumps({'verified_cases': len(rows), 'live_calls': 0, 'report': str(output / 'report.html')}))

if __name__ == '__main__':
    main()
