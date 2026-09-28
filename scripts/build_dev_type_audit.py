"""Read-only original experiment inspection; derived type report and independent arithmetic."""
import argparse, json, html, csv, statistics, sys
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from financial_annotation_harness.io_utils import read_json, read_jsonl, file_hash
from financial_annotation_harness.facts import FactRepository
from financial_annotation_harness.validators import answer_equal

def build(base, evaluations, out):
    out.mkdir(parents=True,exist_ok=False)
    finals=[r for p in base.glob('run_*/[ABCD]/finals.jsonl') for r in read_jsonl(p)]
    final_keys={(r['run_index'],r['condition'],r['question_id']):r['attempt'] for r in finals}
    summaries=[]
    for label,folder in evaluations:
        scores=read_jsonl(folder/'per_question.jsonl')
        for c in 'ABCD':
            for kind in sorted({r['question_type'] for r in scores}):
                group=[r for r in scores if r['condition']==c and r['question_type']==kind]
                first=[r for r in group if r['attempt']==1]
                last=[r for r in group if r['attempt']==final_keys[r['run_index'],c,r['question_id']]]
                assert len(first)==len(last)==6
                fm={(r['run_index'],r['question_id']):r for r in first}
                wrong=sum(r['e2e']==0 for r in first)
                recovered=sum(fm[r['run_index'],r['question_id']]['e2e']==0 and r['e2e']==1 for r in last)
                pending=any(r['e2e'] is None for r in first+last)
                def metric(key,rows):return None if any(r[key] is None for r in rows) else statistics.mean(r[key] for r in rows)
                # Mechanical contract diagnostic, separate from financial correctness.
                contract=sum(all(v['status']=='PASS' for v in r['offline_validator_results'].values()) for r in last)
                summaries.append({'reviewer':label,'condition':c,'question_type':kind,'unique_questions':len({r['question_id'] for r in last}),'question_runs':len(last),
                    'first_correct':sum(r['e2e']==1 for r in first),'final_correct':sum(r['e2e']==1 for r in last),
                    'first_pass':metric('e2e',first),'final_e2e':metric('e2e',last),'answer_accuracy':metric('answer_accuracy',last),
                    'evidence_f1':metric('evidence_f1',last),'python_consistency':metric('python_answer_consistency',last),
                    'contract_pass':contract/len(last),'recovery_numerator':recovered,'recovery_denominator':wrong,
                    'recovery_rate':None if pending or not wrong else recovered/wrong})
    (out/'per_type.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2),encoding='utf-8')
    with (out/'per_type.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(summaries[0]));w.writeheader();w.writerows(summaries)
    def pct(x):return '不適用／待評' if x is None else f'{x:.1%}'
    sections=''
    for label,_ in evaluations:
        body=''
        for r in summaries:
            if r['reviewer']!=label:continue
            body+='<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in [r['question_type'],r['condition'],f"{r['unique_questions']} 題 / {r['question_runs']} 題次",f"{r['first_correct']}/6 ({pct(r['first_pass'])})",f"{r['final_correct']}/6 ({pct(r['final_e2e'])})",pct(r['answer_accuracy']),pct(r['evidence_f1']),pct(r['contract_pass']),f"{r['recovery_numerator']}/{r['recovery_denominator']} ({pct(r['recovery_rate'])})"] )+'</tr>'
        sections+='<h2>'+html.escape(label)+'</h2><div class="scroll"><table><tr><th>題型</th><th>組別</th><th>樣本</th><th>First-pass</th><th>Final E2E</th><th>答案正確率</th><th>Evidence F1</th><th>契約通過率</th><th>Recovery</th></tr>'+body+'</table></div>'
    page='<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>各題型準確率</title><style>body{font:16px/1.7 Microsoft JhengHei,sans-serif;margin:28px;background:#f4f7fb;color:#16324b}table{border-collapse:collapse;background:white}th,td{padding:10px;border:1px solid #d4dce6}th{background:#e8eff8}.scroll{overflow:auto}h1{font-size:28px}</style><h1>各題型準確率與契約符合度</h1><p>來源：'+html.escape(str(base.relative_to(ROOT)))+'。相同題目重複執行不等於新增獨立題目。Evidence F1 是各題次平均，不是答對題數。契約通過率指 8 個程式驗證器全通過，不能當成語意正確率。Recovery 分母為第一次 E2E 錯誤題次；0/0 不適用。所有語意評分皆為 AI 輔助，非人工審查。</p>'+sections+'</html>'
    (out/'report.html').write_text(page,encoding='utf-8')
    inputs={str(p.relative_to(ROOT)):file_hash(p) for p in base.glob('run_*/[ABCD]/finals.jsonl')}
    for _,folder in evaluations: inputs[str((folder/'per_question.jsonl').relative_to(ROOT))]=file_hash(folder/'per_question.jsonl')
    (out/'provenance.json').write_text(json.dumps({'inputs':inputs,'script_hash':file_hash(Path(__file__))},indent=2),encoding='utf-8')
    return summaries

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--experiment',required=True);parser.add_argument('--evaluation',action='append',required=True,help='LABEL=PATH');parser.add_argument('--output',required=True);args=parser.parse_args()
    build(ROOT/args.experiment,[(x.split('=',1)[0],ROOT/x.split('=',1)[1]) for x in args.evaluation],ROOT/args.output)
