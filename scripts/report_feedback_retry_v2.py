"""Compare fixed-input v1/v2 diagnostic traces without changing their outcomes."""
import csv,html,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from financial_annotation_harness.io_utils import read_json,read_jsonl,file_hash,write_new_json
OUT=ROOT/'outputs/dev-feedback-retry-v2'
OLD=ROOT/'outputs/dev-feedback-retry-v1'

def main():
    new=read_json(OUT/'summary.json');old=read_json(OLD/'final_analysis.json')
    inspection=read_json(OUT/'semantic_inspection.json');notes={r['case_id']:r for r in inspection['cases']}
    before={r['case_id']:r for r in old['cases']}
    rows=[]
    for r in new['rows']:
        key=r['case_id'];b=before[key]
        good=r['final_status']=='ACCEPTED' and all(r['checks'].values()) and notes[key]['semantic_repaired']
        rows.append({'case_id':key,'old_recovered':b['diagnostic_recovered'],'new_recovered':good,
          'old_retries':b['retries_used'],'new_retries':r['retries_used'],
          'same_final_artifact':b['attempts'][-1]['artifact']==r['attempts'][-1]['artifact'],
          'new_failure_attempts':r['new_deterministic_failure_attempts'],'reason':notes[key]['reason']})
    result={'scope':'Paired synthetic Dev diagnostic; not main accuracy','cases':rows,
      'old_recovered':sum(r['old_recovered'] for r in rows),'new_recovered':sum(r['new_recovered'] for r in rows),
      'regressions':sum(r['old_recovered'] and not r['new_recovered'] for r in rows),
      'new_live_generator_calls':new['new_generator_requests'],'new_live_judge_calls':new['new_judge_requests'],
      'cached_initial_judge_calls':new['cached_initial_judge'],'human_review_completed':False,
      'source_hashes':{str(p.relative_to(ROOT)):file_hash(p) for p in [OUT/'manifest.json',OUT/'summary.json',OUT/'semantic_inspection.json',OUT/'predicate_regression.json',OLD/'final_analysis.json']}}
    write_new_json(OUT/'comparison.json',result)
    with (OUT/'comparison.csv').open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    table=''.join('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in [r['case_id'],'修復' if r['old_recovered'] else '未修復','修復' if r['new_recovered'] else '未修復',r['old_retries'],r['new_retries'],'相同' if r['same_final_artifact'] else '不同'])+'</tr>' for r in rows)
    detail=''
    for r in new['rows']:
        detail+='<details><summary>'+html.escape(r['case_id'])+'</summary><p>'+html.escape(notes[r['case_id']]['reason'])+'</p><pre>'+html.escape(json.dumps(r['attempts'],ensure_ascii=False,indent=2))+'</pre></details>'
    gr=next(r for r in new['rows'] if r['case_id']=='GR03__wrong_evidence')
    old_gr=before['GR03__wrong_evidence']
    feedback={}
    for label,row in [('舊版',old_gr),('新版',gr)]:
        feedback[label]=[i for a in row['attempts'] if a['attempt']==2 for v in a['validator_results'].values() for i in v['issues'] if i['rule_id']=='EVID-01']
    page='''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>EVID-01 回饋改善對照</title><style>body{font:17px/1.8 Microsoft JhengHei,sans-serif;max-width:1150px;margin:30px auto;padding:20px;background:#f4f7fb;color:#19314b}table{width:100%;border-collapse:collapse;background:white}td,th{border:1px solid #ccd;padding:10px}details,.box{padding:20px;background:white;margin:15px 0;border-radius:10px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px}.notice{padding:20px;background:#fff3d8}a{color:#145caa}</style><h1>EVID-01：把欄位差異寫清楚，是否更容易修復？</h1><div class="box"><b>完整修復：'''+str(result['old_recovered'])+'/9 → '+str(result['new_recovered'])+'/9；退步案例：'+str(result['regressions'])+'</b><p>本輪 '+str(result['new_live_generator_calls'])+' 次真實 Generator 請求、'+str(result['new_live_judge_calls'])+' 次真實 Judge 請求，另有 9 次明確標示的初始 Judge 重播。</p><a href="comparison.csv">下載對照 CSV</a> · <a href="comparison.json">分析與來源紀錄</a> · <a href="../dev-feedback-retry-v1/report.html">上一輪報告</a></div><table><tr><th>案例</th><th>舊版</th><th>新版</th><th>舊版 retry</th><th>新版 retry</th><th>最終原始輸出</th></tr>'+table+'</table>'
    page+='''<h2>唯一處理變因</h2><p>EvidenceValidator 1.3 的 EVID-01 回饋改為列出兩欄 ID、各自多出的項目與重複項目，並指明 retrieved_fact_ids 只列最終選用 evidence。通過條件、failure code、模型版本、參數、Generator/Judge prompt、工具與兩次 retry 上限均維持不變。另以舊版全部 19 份初稿／修訂重新驗證，所有通過／失敗狀態及 rule_id 均相同。</p><h2>GR03 第一次修訂後收到的回饋</h2><pre>'''+html.escape(json.dumps(feedback,ensure_ascii=False,indent=2))+'''</pre><h2>逐筆修復檢查</h2>'''+detail+'''<div class="notice">9 個案例源自 7 題 Dev，錯誤為 AI 合成、候選 facts 已含正確資料；此為小型固定輸入對照，並非正式 A/B/C/D 準確率，也不足以推估一般化效果。初次 Judge 重播不算新推論。語意檢查由 AI 執行，沒有人工審查。原始 Gold、舊輸出均保留；本輪未執行 Test 或 freeze。</div><h2>後續原則</h2><p>若本輪修復有效且無退步，保留這項局部改善並停止擴大 prompt 調整，進入版本、環境與論文結果整理。舊 48 題 Test 已使用，之後執行應標示為版本回歸比較；未見資料泛化需要另外的 holdout。</p></html>'''
    (OUT/'report.html').write_text(page,encoding='utf-8')
    print({k:v for k,v in result.items() if k not in ('cases','source_hashes')})

if __name__=='__main__':main()
