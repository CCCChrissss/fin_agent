"""Versioned Dev-only offline remeasurement; no Generator or Test execution."""
import json, sys, html
from pathlib import Path
from dataclasses import asdict
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from financial_annotation_harness.io_utils import read_json, read_jsonl, file_hash, digest, timestamp, write_new_json, write_new_jsonl
from financial_annotation_harness.config import load_settings, load_rules
from financial_annotation_harness.dataset import verify_derived
from financial_annotation_harness.governance import project_hashes
from financial_annotation_harness.facts import FactRepository
from financial_annotation_harness.evaluation import evaluate_experiment, REVIEW_FIELDS
from financial_annotation_harness.ollama_provider import OllamaProvider
from repair_offline_reviews import review_schema
from complete_ai_study import parse_review
BASE=ROOT/'outputs/dev-prompt-v3/full-dev-v3'
OUT=ROOT/'outputs/dev-audit-cross-review-v1'

class Reviewer(OllamaProvider):
    def describe_request(self,role,seed):
        payload=super().describe_request(role,seed)
        payload['format']=review_schema()
        return payload

def main():
    OUT.mkdir(exist_ok=True)
    original=read_json(BASE/'manifest.json')
    split=read_json(ROOT/'artifacts/dataset_split.json')
    assert original['partition']=='development'
    assert {r['question_id'] for r in original['expected_runs']}==set(split['development'])
    source=ROOT/'data/financial_qa_gold_dataset_v2.xlsx'
    derived=ROOT/'artifacts/derived'/file_hash(source)
    assert digest(verify_derived(source,derived))==original['source_manifest_hash']
    files=[p for p in BASE.rglob('*') if p.is_file() and p.suffix in ('.json','.jsonl')]
    inputs={str(p.relative_to(ROOT)):file_hash(p) for p in files}
    settings=load_settings(ROOT/'config/experiment.qwen35-9b.probe.json')
    provenance={'kind':'offline_remeasurement','created_from_manifest':file_hash(BASE/'manifest.json'),
      'original_project_hashes':original['project_hashes'],'evaluation_project_hashes':project_hashes(ROOT),
      'script_hash':file_hash(Path(__file__)),'source_hash':file_hash(source),'original_file_hashes':inputs,
      'review_model':settings.model.model_dump(),'schema':review_schema(),
      'change':'YearValidator 1.3 normalizes fiscal_year only; exact date checks remain.',
      'generator_rerun':False,'test_executed':False,'human_review_completed':False,
      'policy':'Same original blind messages and rubric. One request per unique input. No automatic resampling. Disagreements are not automatically adjudicated.'}
    pp=OUT/'provenance.json'
    if pp.exists(): assert read_json(pp)==provenance,'Provenance changed'
    else: write_new_json(pp,provenance)
    repo=FactRepository(derived/'financial_facts.sqlite')
    questions=[{'question_id':q['question_id'],'question':q[original['settings']['language']],'language':original['settings']['language']} for q in read_jsonl(derived/'question_inputs.jsonl')]
    gold=read_jsonl(derived/'gold_annotations.jsonl')
    rules=load_rules(ROOT)
    gemma=read_jsonl(BASE/'ai-review-labels.jsonl')
    def evaluate(name,labels):
        dest=OUT/name
        if not dest.exists(): evaluate_experiment(BASE,gold,questions,repo,rules,dest,labels)
        return read_json(dest/'aggregate_metrics.json')
    gm=evaluate('year-fixed-gemma',gemma)
    unique=sorted({r['request_hash'] for r in gemma})
    client=Reviewer(settings,allow_live=True)
    try:
        rp=OUT/'runtime.json'
        if not rp.exists(): write_new_json(rp,client.runtime)
        for i,key in enumerate(unique,1):
            target=OUT/(key+'.json'); intent=OUT/(key+'.request.json')
            if target.exists(): continue
            if intent.exists(): raise RuntimeError('Uncertain request; manual inspection required: '+key)
            original_request=read_json(BASE/'offline-ai-review'/(key+'.1.request.json'))
            messages=original_request['messages']
            assert len(messages)==2
            assert set(json.loads(messages[1]['content']))=={'original_question','generated_annotation','financial_facts'}
            write_new_json(intent,{'messages':messages,'parameters':client.describe_request('judge',settings.model.base_seed),'original_request_hash':file_hash(BASE/'offline-ai-review'/(key+'.1.request.json')),'timestamp':timestamp()})
            record={}
            try:
                client.begin_question()
                turn=client.complete(messages,[],role='judge',seed=settings.model.base_seed)
                record['raw_response']=asdict(turn)
                if turn.finish_reason!='stop' or turn.tool_calls: raise ValueError('Incomplete structured review')
                record['verdict']=parse_review(turn.content)
            except Exception as exc: record['error']=str(exc)
            write_new_json(target,record)
            print(json.dumps({'processed_unique':i,'total_unique':len(unique),'error':record.get('error')},ensure_ascii=True),flush=True)
        client.verify_identity()
    finally: client.close()
    labels=[]; differences=[]; unresolved=[]
    for r in gemma:
        rec=read_json(OUT/(r['request_hash']+'.json'))
        if 'verdict' not in rec:
            unresolved.append(r['review_id']);continue
        v=rec['verdict']
        labels.append({**r,'reviewer':settings.model.judge_model+' offline cross review','rationale':v['reason'],**{k:v[k] for k in REVIEW_FIELDS}})
        changed=[k for k in REVIEW_FIELDS if r[k]!=v[k]]
        if changed: differences.append({'review_id':r['review_id'],'artifact_hash':r['artifact_hash'],'request_hash':r['request_hash'],'fields':changed,'gemma_reason':r['rationale'],'qwen_reason':v['reason'],'gemma':{k:r[k] for k in REVIEW_FIELDS},'qwen':{k:v[k] for k in REVIEW_FIELDS}})
    if not (OUT/'qwen-labels.jsonl').exists(): write_new_jsonl(OUT/'qwen-labels.jsonl',labels)
    qm=evaluate('year-fixed-qwen',labels)
    summary={'kind':'offline_remeasurement','unique_inputs':len(unique),'labels':len(labels),'unresolved':unresolved,'disagreement_records':len(differences),'disagreement_unique':len({r['request_hash'] for r in differences}),'original':read_json(BASE/'evaluation-ai/aggregate_metrics.json')['metrics'],'year_fixed_gemma':gm['metrics'],'year_fixed_qwen':qm['metrics'],'provenance_hash':digest(provenance)}
    assert all(file_hash(ROOT/p)==h for p,h in inputs.items()),'Original outputs modified'
    assert file_hash(source)==provenance['source_hash']
    if not (OUT/'summary.json').exists():
        write_new_json(OUT/'summary.json',summary);write_new_jsonl(OUT/'disagreements.jsonl',differences)
    table=''
    for c in 'ABCD':
        vals=[summary[k][c]['e2e_accuracy']['mean'] for k in ('original','year_fixed_gemma','year_fixed_qwen')]
        table+='<tr><th>'+c+'</th>'+''.join('<td>'+('待評' if v is None else format(v,'.1%'))+'</td>' for v in vals)+'</tr>'
    details=''.join('<details><summary>'+html.escape(r['request_hash'][:12]+' / '+', '.join(r['fields']))+'</summary><p>Gemma: '+html.escape(r['gemma_reason'])+'</p><p>Qwen: '+html.escape(r['qwen_reason'])+'</p></details>' for r in {r['request_hash']:r for r in differences}.values())
    page='<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>Dev 評估稽核</title><style>body{font:17px/1.8 Microsoft JhengHei,sans-serif;max-width:1100px;margin:32px auto;padding:20px;background:#f4f7fb;color:#18324b}td,th{padding:12px;border:1px solid #bbc}table{border-collapse:collapse}details{background:white;padding:15px;margin:12px 0}</style><h1>Dev 年份修正與跨模型審核</h1><p>僅離線重評既有輸出，未重跑 Generator。Qwen 是第二評分者，不是裁判標準。相同模型內容去重，不能把重複紀錄當獨立樣本。先前 Test 已使用。</p><table><tr><th>組別</th><th>原 E2E</th><th>年份修正 + Gemma</th><th>年份修正 + Qwen</th></tr>'+table+'</table><p>不同審核輸入 '+str(len(unique))+'；分歧輸入 '+str(summary['disagreement_unique'])+'；未完成紀錄 '+str(len(unresolved))+'。</p><h2>分歧理由（尚未裁決）</h2>'+details+'</html>'
    (OUT/'report.html').write_text(page,encoding='utf-8')
    print(json.dumps({'complete':True,'disagreement_unique':summary['disagreement_unique'],'unresolved':len(unresolved)}),flush=True)

if __name__=='__main__': main()
