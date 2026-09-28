"""Render the bounded prompt comparison without modifying old experiment reports."""
import html
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from financial_annotation_harness.io_utils import read_json, read_jsonl, write_new_json, file_hash
from financial_annotation_harness.governance import project_hashes


def table(headers, rows):
    def cell(value):
        return html.escape(str(value))
    return '<div class="scroll"><table><tr>' + ''.join('<th>'+cell(h)+'</th>' for h in headers) + '</tr>' + ''.join(
        '<tr>' + ''.join('<td>'+cell(v)+'</td>' for v in row) + '</tr>' for row in rows) + '</table></div>'


def main():
    out = ROOT / 'outputs/dev-prompt-v2'
    out.mkdir(parents=True, exist_ok=True)
    parts, summary = [], {'scope': 'Dev engineering comparison, not formal Test or general model accuracy'}
    judge_paths = {'previous': ROOT/'outputs/offline-repair-v1/dev-judge-candidate-extended',
                   'prompt_v2': out/'judge-extended'}
    judges = {}
    for name, folder in judge_paths.items():
        p = folder/'summary.json'
        if p.exists():
            judges[name] = read_json(p)['cases']
    if len(judges) != 2:
        raise ValueError('Both Judge comparisons must finish before reporting')
    previous = {r['case']: r for r in judges['previous']}
    rows = []
    for r in judges['prompt_v2']:
        old = previous[r['case']]
        rows.append([r['case'], r['criterion'], r['expected'], old['observed'], r['observed'], r['correct'], r['error'] or ''])
    summary['judge'] = {name: {'correct': sum(r['correct'] for r in values), 'total': len(values),
                               'parse_errors': sum(r['error'] is not None for r in values)} for name, values in judges.items()}
    parts.append('<h2>Judge：相同 schema，只改 prompt</h2><p>正確數計算指定的判斷欄位，不以任意理由拒絕就算正確。前五例是已用於診斷的案例，另外三例來自第二道 Dev 題目；都不屬於正式 Test。</p>')
    parts.append(table(['版本','符合預期','案例數','解析失敗'], [[name,v['correct'],v['total'],v['parse_errors']] for name,v in summary['judge'].items()]))
    parts.append(table(['案例','核對欄位','預期','之前','prompt v2','v2 符合','錯誤'], rows))
    workflow_paths = {'previous': ROOT/'outputs/offline-repair-v1/dev-workflow-pilot', 'prompt_v2': out/'workflow-pilot'}
    rows, measures = [], {}
    for name, folder in workflow_paths.items():
        records = read_json(folder/'summary.json')['rows']
        scores = {(r['condition'],r['question_id']): r for r in read_json(folder/'mechanical-assessment.json')['rows']}
        measures[name] = {}
        for c in 'ABCD':
            subset = [r for r in records if r['condition']==c]
            ss = [scores[(c,r['question_id'])] for r in subset]
            finals = read_jsonl(folder/'run_01'/c/'finals.jsonl')
            leak = sum(any(t in json.dumps(r.get('artifact'),ensure_ascii=False) for t in ['示例科目', '2040', '2041']) for r in finals)
            item = {'n': len(subset), 'tool_used_first': sum(r['first_tool_used'] for r in subset),
                    'answer_correct': sum(s['answer_accuracy'] for s in ss),
                    'evidence_f1_mean': sum(s['evidence_f1'] for s in ss)/len(ss),
                    'python_consistent': sum(s['python_answer_consistency'] for s in ss),
                    'no_mechanical_failures': sum(not s['offline_failure_codes'] for s in ss),
                    'total_attempts': sum(r['attempts'] for r in subset), 'toy_example_leaks': leak}
            measures[name][c] = item
            rows.append([name,c,item['tool_used_first'],item['answer_correct'],f'{item["evidence_f1_mean"]:.1%}',
                         item['python_consistent'],item['no_mechanical_failures'],item['total_attempts'],leak])
    summary['workflow'] = measures
    parts.append('<h2>Generator：具體表格範例</h2><p>同樣 AR07、SF06 兩題，每組一次。A 保持原 prompt，B/C/D 使用相同候選 Workflow；模型、規則、schema、Retry 和線上 Judge 不變。各欄正確／使用次數的分母為 2。這是機械評分，尚非獨立語意 E2E。</p>')
    parts.append(table(['版本','組別','首次工具','答案正確','Evidence F1','Python 一致','無機械錯誤','總 attempts','範例污染'],rows))
    old_manifest = read_json(ROOT/'results/dev-ai-assisted-001/manifest.json')
    summary['frozen_core_unchanged'] = old_manifest['project_hashes'] == project_hashes(ROOT)
    summary['gold_sha256'] = file_hash(ROOT/'data/financial_qa_gold_dataset_v2.xlsx')
    summary['prompt_hashes'] = {p.name:file_hash(p) for p in (ROOT/'experiments/dev_prompt_v2').glob('*.md')}
    old = read_json(workflow_paths['previous']/'manifest.json')
    new = read_json(workflow_paths['prompt_v2']/'manifest.json')
    summary['generator_controls_equal'] = old['settings'] == new['settings'] and old['selected_ids'] == new['selected_ids']
    summary['unchanged_prompt_components'] = {k:old['prompts'][k]==new['prompts'][k] for k in ('baseline','contract','judge')}
    a_events = {name:read_jsonl(folder/'run_01/A/events.jsonl') for name,folder in workflow_paths.items()}
    a_finals = {name:{r['question_id']:r for r in read_jsonl(folder/'run_01/A/finals.jsonl')} for name,folder in workflow_paths.items()}
    controls = {}
    for qid in new['selected_ids']:
        reqs = [next(r for r in a_events[name] if r['question_id']==qid and r['event']=='generator_request' and r['attempt']==1 and r['step']==0) for name in ('previous','prompt_v2')]
        controls[qid] = {'initial_messages_equal':reqs[0]['messages']==reqs[1]['messages'],
                         'parameters_equal':reqs[0]['request_parameters']==reqs[1]['request_parameters'],
                         'final_artifact_equal':a_finals['previous'][qid]['artifact']==a_finals['prompt_v2'][qid]['artifact']}
    summary['unchanged_A_control'] = controls
    if not summary['frozen_core_unchanged'] or not summary['generator_controls_equal'] or not all(summary['unchanged_prompt_components'].values()):
        raise ValueError('Comparison controls drifted')
    jp = out/'comparison_summary.json'
    if not jp.exists():
        write_new_json(jp, summary)
    elif read_json(jp) != summary:
        raise ValueError('Summary drift; use a new result version')
    page = '''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>Dev Prompt 對照結果</title>
    <style>body{font:16px/1.7 "Microsoft JhengHei",sans-serif;max-width:1280px;margin:32px auto;padding:24px;background:#f5f7fa;color:#172b4d}table{border-collapse:collapse;width:100%;background:#fff;font-size:14px}td,th{border:1px solid #d7dfe9;padding:9px;text-align:left}th{background:#eaf0f7}.scroll{overflow:auto}h2{margin-top:32px}</style>
    <h1>Dev Prompt 對照結果</h1><p>已授權的候選改善。固定模型与 schema，分開檢查 Generator 與 Judge 的 prompt 效果；未重跑正式 Test，原始結果保留。</p>'''
    page += ''.join(parts)
    page += '<h2>未修改 prompt 的 A 組對照</h2>' + table(['題目','初始 request 相同','參數相同','最終 artifact 相同'], [[qid,v['initial_messages_equal'],v['parameters_equal'],v['final_artifact_equal']] for qid,v in controls.items()])
    page += '<h2>解讀限制</h2><p>本次 Generator 只有兩題，不能據此宣稱正式準確率提升或 D 必定最好。未修改 prompt 的 A 組也出現輸出差異，顯示固定 seed 不能在本環境保證完全相同輸出；不能把全部前後差異都歸因於 prompt。Judge 合成案例的改善也不等於真實資料可靠性。下一階段先在 12 題 Dev 重複檢查；所有退步保留，不能挑結果最好的一次當正式結果。</p>'
    page += '<p>凍結核心與共同控制已比對一致；Gold 保持原 SHA-256。候選 prompt 位於 experiments/dev_prompt_v2，未替換正式 prompts。</p></html>'
    (out/'comparison_report.html').write_text(page,encoding='utf-8')
    print(json.dumps(summary))


if __name__=='__main__':
    main()
