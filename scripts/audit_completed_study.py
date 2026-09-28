"""Read immutable experiment traces; write a separate audit and review dashboard."""
import collections
import html
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from financial_annotation_harness.io_utils import read_json, read_jsonl, digest, file_hash, write_new_json
from financial_annotation_harness.governance import project_hashes


def audit(part):
    folder = ROOT / 'results' / f'{part}-ai-assisted-001'
    manifest = read_json(folder / 'manifest.json')
    attempts = [r for p in sorted(folder.glob('run_*/[ABCD]/attempts.jsonl')) for r in read_jsonl(p)]
    finals = [r for p in sorted(folder.glob('run_*/[ABCD]/finals.jsonl')) for r in read_jsonl(p)]
    expected = {(r['run_index'], r['condition'], r['question_id']) for r in manifest['expected_runs']}
    observed = [(r['run_index'], r['condition'], r['question_id']) for r in finals]
    requests = [t.get('request_id') for r in attempts for t in r['generator_responses']]
    conditions = {}
    for condition in 'ABCD':
        subset = [r for r in attempts if r['condition'] == condition]
        first = [r for r in subset if r['attempt'] == 1]
        fs = [r for r in finals if r['condition'] == condition]
        judged = [r for r in subset if r.get('judge_result')]
        grouped = collections.defaultdict(list)
        for r in fs:
            artifact = dict(r.get('artifact') or {})
            artifact.pop('question_id', None)
            grouped[r['question_id']].append(digest(artifact))
        conditions[condition] = {
            'finals': len(fs), 'attempts': len(subset),
            'first_attempt_tool_usage': sum(bool(r['tool_calls']) for r in first),
            'first_attempt_count': len(first),
            'judge_calls': sum(bool(r.get('judge_usage')) for r in subset),
            'judge_valid': len(judged), 'judge_pass': sum(r['judge_result']['overall_pass'] for r in judged),
            'judge_reject': sum(not r['judge_result']['overall_pass'] for r in judged),
            'final_status': dict(collections.Counter(r['final_status'] for r in fs)),
            'same_artifact_across_runs': sum(len(set(v)) == 1 for v in grouped.values()),
            'unique_questions': len(grouped),
            'failure_rules_per_attempt': dict(collections.Counter(i['rule_id'] for r in subset
                for v in r['validator_results'].values() for i in v['issues'])),
        }
    return {'partition': part, 'expected': len(expected), 'observed': len(observed),
            'missing': sorted(expected - set(observed)), 'extra': sorted(set(observed) - expected),
            'duplicate_finals': len(observed) - len(set(observed)),
            'max_attempt': max(r['attempt'] for r in attempts),
            'seeds': sorted(set(r['seed'] for r in attempts)),
            'generator_request_count': len(requests), 'unique_request_ids': len(set(requests)),
            'core_hashes_match': manifest['project_hashes'] == project_hashes(ROOT),
            'conditions': conditions,
            'source_hashes': {str(p.relative_to(ROOT)): file_hash(p) for p in sorted(folder.glob('run_*/[ABCD]/*.jsonl'))}}


def main():
    output = ROOT / 'outputs/offline-repair-v1'
    output.mkdir(parents=True, exist_ok=True)
    audits = [audit(p) for p in ('dev', 'test')]
    target = output / 'integrity-audit.json'
    if not target.exists():
        write_new_json(target, audits)
    elif read_json(target) != audits:
        raise ValueError('Original records or frozen core changed since audit')
    sections = []
    for a in audits:
        sections.append(f'<h2>{a["partition"].upper()}</h2><p>Finals {a["observed"]}/{a["expected"]}; '
                        f'missing {len(a["missing"])}; duplicates {a["duplicate_finals"]}; '
                        f'max attempts {a["max_attempt"]}; frozen core match {a["core_hashes_match"]}.</p>')
        rows = []
        for c, v in a['conditions'].items():
            rows.append(f'<tr><th>{c}</th><td>{v["first_attempt_tool_usage"]}/{v["first_attempt_count"]}</td>'
                        f'<td>{v["attempts"]}</td><td>{v["judge_calls"]}</td><td>{v["judge_reject"]}</td>'
                        f'<td>{v["same_artifact_across_runs"]}/{v["unique_questions"]}</td></tr>')
        sections.append('<table><tr><th>Condition</th><th>First-pass tool use</th><th>Attempts</th>'
                        '<th>Judge calls</th><th>Judge rejection</th><th>Identical outputs across runs</th></tr>' + ''.join(rows) + '</table>')
        eval_path = output / a['partition'] / 'evaluation/aggregate_metrics.json'
        if eval_path.exists():
            m = read_json(eval_path)
            sections.append(f'<p>Unresolved semantic reviews: {m["pending_review_count"]}</p>')
            fields = ['answer_accuracy', 'evidence_f1', 'python_answer_consistency', 'e2e_accuracy', 'first_pass_accuracy', 'recovery_rate']
            rows = []
            for c, values in m['metrics'].items():
                cells = [f'{values[k]["mean"]:.1%}' if values[k]['mean'] is not None else 'Unresolved / undefined' for k in fields]
                rows.append('<tr><th>' + c + '</th>' + ''.join('<td>' + x + '</td>' for x in cells) + '</tr>')
            sections.append('<table><tr><th>Condition</th>' + ''.join('<th>'+ k +'</th>' for k in fields) + '</tr>'+ ''.join(rows) +'</table>')
        else:
            sections.append('<p>Repaired evaluation is not yet complete.</p>')
    page = '''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>實驗補評與稽核</title>
    <style>body{font:16px/1.7 "Microsoft JhengHei",sans-serif;max-width:1250px;margin:32px auto;padding:24px;background:#f4f6fa;color:#182b42}table{border-collapse:collapse;width:100%;background:white;font-size:14px}td,th{border:1px solid #dbe1ea;padding:10px;text-align:left}h2{margin-top:32px}</style>
    <h1>實驗補評與稽核</h1><p>原始 v1 推論及評分完整保留。本頁是額外的離線評估修復，不是新一輪 Generator 實驗。</p>
    <p>AI 評分不是人工審核。補評沿用原語意 rubric，加入必填 JSON schema；有效的舊評分保留，原先無效的評分以 fresh context 重做，最多兩次且保留全部紀錄。</p>'''
    page += ''.join(sections)
    page += '<h2>Dev Judge 元件檢查</h2><p>僅 5 個合成檢查案例；不是正式準確率。correct 檢查指定欄位，整體拒絕但理由或欄位錯誤仍不算通過。</p>'
    for label, dirname in [('原版', 'dev-judge-probes'), ('候選版', 'dev-judge-candidate')]:
        probe = output / dirname / 'summary.json'
        if probe.exists():
            rows = read_json(probe)['cases']
            page += f'<h3>{label}：{sum(r["correct"] for r in rows)}/{len(rows)}</h3><table><tr><th>案例</th><th>核對欄位</th><th>預期</th><th>觀察</th><th>錯誤</th></tr>'
            for r in rows:
                page += '<tr>' + ''.join('<td>' + html.escape(str(r[k])) + '</td>' for k in ('case', 'criterion', 'expected', 'observed', 'error')) + '</tr>'
            page += '</table>'
    page += '<p>候選版仍有公司欄位問題，尚未提升為正式 Judge。原版公司案例雖 overall 拒絕，但錯把聯電與 UMC 當成不同公司，不能當作正確理由。</p>'
    pilot = output / 'dev-workflow-pilot/summary.json'
    if pilot.exists():
        page += '<h2>Dev Workflow 工程試跑</h2><p>2 題 × 4 條件 × 1 次；保留原模型、Judge、規則與 Retry。只在 B/C/D 強調既有 Workflow 的工具查詢與格式要求。通過 Gate 不等同 E2E 正確。</p><table><tr><th>條件</th><th>題目</th><th>首次使用工具</th><th>Attempts</th><th>最終狀態</th><th>Failure codes</th><th>Judge calls</th></tr>'
        for r in read_json(pilot)['rows']:
            page += '<tr>' + ''.join('<td>' + html.escape(str(r[k])) + '</td>' for k in ('condition', 'question_id', 'first_tool_used', 'attempts', 'final_status', 'final_failure_codes', 'judge_calls')) + '</tr>'
        page += '</table>'
        assessment = output / 'dev-workflow-pilot/mechanical-assessment.json'
        if assessment.exists():
            page += '<h3>工程試跑的離線機械評分</h3><p>尚未獨立語意審查，不宣稱 E2E。</p><table><tr><th>條件</th><th>題目</th><th>Answer correct</th><th>Evidence F1</th><th>Python executed</th><th>Python consistency</th><th>Failures</th></tr>'
            for r in read_json(assessment)['rows']:
                page += '<tr>' + ''.join('<td>' + html.escape(str(r[k])) + '</td>' for k in ('condition','question_id','answer_accuracy','evidence_f1','python_execution_rate','python_answer_consistency','offline_failure_codes')) + '</tr>'
            page += '</table>'
    page += '<h2>後續判斷</h2><p>D 的 Judge 只在確定性驗證全通過時介入。須先改善 Dev 的工具使用與共同格式遵循，再用明確正反案例測試 Judge 辨錯能力。不因 Test 結果放寬原規則或增加 D 的重試額度。</p><p>三次 run 使用不同 seed；彙總指標一致不代表逐字輸出一致。統計以題目配對處理。尚未重跑正式 Test。</p>'
    page += '<ol><li>補評格式：Dev/Test 缺失理由已透過独立補評處理；完整性以本頁各 split 的未解決數為準。</li><li>Workflow：小試中 AR07 首次搜尋改善，但 B 仍有答案與 Python 不一致；SF06 的年份表頭仍被省略。候選版不提升正式設定。</li><li>下一版 deterministic feedback：依原規則精確指出缺少的表頭或欄位，提供不含答案的格式模板；先用 Dev 驗證。</li><li>Judge：公司／實體不一致仍有漏判，需更多正反及同義名稱案例。候選版 4/5 只代表這批檢查，不能推論一般準確率。</li><li>完成上述項目後才評估 12 題 Dev 的 A/B/C/D 重跑；新版本若重用已見 Test，必須標示後續 regression study。</li></ol>'
    page += '<p>補評沿用同一個模型，仍有共同偏誤；格式完整不代表 AI 判斷全部正確。原始 v1 報告與所有失敗回應保留。</p></html>'
    (output / 'audit_report.html').write_text(page, encoding='utf-8')
    print(json.dumps([{k:v for k,v in a.items() if k != 'source_hashes'} for a in audits]))


if __name__ == '__main__':
    main()
