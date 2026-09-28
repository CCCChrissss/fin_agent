"""Render verified feedback recovery and AI inspection separately from gate results."""
import csv
import html
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from financial_annotation_harness.io_utils import read_json,read_jsonl,write_new_json,file_hash
OUT=ROOT/'outputs/dev-feedback-retry-v1'

def main():
    s=read_json(OUT/'summary.json');audit=read_json(OUT/'semantic_inspection.json')
    verdicts={r['case_id']:r for r in audit['cases']}
    assert set(verdicts)=={r['case_id'] for r in s['rows']}
    results=[]
    for r in s['rows']:
        v=verdicts[r['case_id']]
        recovered=r['final_status']=='ACCEPTED' and all(r['checks'].values()) and v['semantic_repaired']
        results.append({**r,'ai_semantic_inspection':v,'diagnostic_recovered':recovered})
    report={'scope':s['scope'],'total_cases':len(results),'gate_accepted':s['gate_accepted'],
      'diagnostic_recovered':sum(r['diagnostic_recovered'] for r in results),
      'first_retry_recovered':sum(r['diagnostic_recovered'] and r['retries_used']==1 for r in results),
      'cases_with_new_deterministic_failures':s['cases_with_new_deterministic_failures'],
      'new_generator_requests':s['new_generator_requests'],'new_judge_requests':s['new_judge_requests'],
      'replayed_initial_judge':s['cached_initial_judge'],'human_review_completed':False,
      'mean_new_latency_seconds':sum(r['latency_ms'] for r in results)/len(results)/1000,
      'artifact_hashes':{p.name:file_hash(p) for p in [OUT/'summary.json',OUT/'semantic_inspection.json',OUT/'manifest.json']},'cases':results}
    write_new_json(OUT/'final_analysis.json',report)
    with (OUT/'results.csv').open('x',encoding='utf-8-sig',newline='') as f:
        fields=['case_id','category','final_status','retries_used','diagnostic_recovered','new_deterministic_failure_attempts','new_generator_requests','new_judge_requests','latency_ms']
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for r in results:w.writerow({k:r[k] for k in fields})
    table='';details=''
    import json
    for r in results:
        table+='<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in [r['case_id'],r['retries_used'],r['final_status'],'修復' if r['diagnostic_recovered'] else '未確認修復',r['new_deterministic_failure_attempts']])+'</tr>'
        details+='<details><summary>'+html.escape(r['case_id'])+'</summary><p>'+html.escape(r['ai_semantic_inspection']['reason'])+'</p>'
        for a in r['attempts']:
            details+='<h3>'+('合成起點／重播初次 Judge' if a['attempt']==1 else f"第 {a['attempt']-1} 次真實修訂")+'</h3><pre>'+html.escape(json.dumps(a,ensure_ascii=False,indent=2))+'</pre>'
        details+='</details>'
    page='''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>Gemma 回饋修復診斷</title><style>body{font:17px/1.8 Microsoft JhengHei,sans-serif;max-width:1200px;margin:30px auto;padding:20px;background:#f4f7fb;color:#19314b}.cards{display:flex;gap:16px;flex-wrap:wrap}.card,details{background:white;padding:20px;border-radius:10px;margin:12px 0}.card strong{font-size:30px;display:block}table{width:100%;border-collapse:collapse;background:white}th,td{padding:12px;border:1px solid #ccd}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px}.note{background:#fff3d8;padding:20px}a{color:#145caa}</style><h1>Gemma：Judge 回饋是否真的讓 Generator 修好？</h1><div class="cards">'''
    for label,value in [('Gate 接受',str(report['gate_accepted'])+'/9'),('離線檢查修復',str(report['diagnostic_recovered'])+'/9'),('第一次 retry 即修復',str(report['first_retry_recovered'])+'/9'),('曾新增 deterministic 錯誤',str(report['cases_with_new_deterministic_failures'])+'/9')]:
        page+='<div class="card">'+label+'<strong>'+value+'</strong></div>'
    page+='</div><p>真實 Generator 請求 '+str(report['new_generator_requests'])+' 次；真實 fresh-context Judge 請求 '+str(report['new_judge_requests'])+' 次；9 次初始 Judge 為上一輪精確輸入的已保存回應重播，不重複算作新推論。每例最多兩次 retry。</p>'
    page+='<p><a href="results.csv">逐案 CSV</a> · <a href="final_analysis.json">完整分析 JSON</a> · <a href="../dev-judge-diagnostic-v1/findings.html">上一輪 Judge 診斷</a></p><table><tr><th>案例</th><th>使用 retry</th><th>Gate</th><th>離線檢查</th><th>新增 deterministic 失敗次數</th></tr>'+table+'</table>'
    page+='''<h2>未完成修復：GR03</h2><p>原題只需 2024 與 2025 年資產。模型修正財務內容後，retrieved_fact_ids 卻列入 2023、2024、2025，selected_evidence 只有 2024、2025。EVID-01 在兩次修訂都失敗；Gate 正確阻止這份不一致標註。</p><p>共同 contract 已明示 retrieved_fact_ids 只列最終選用 evidence。問題不是缺少這條規範：目前回饋 field_path 指向 selected_evidence，observed_value 只列其正確的兩筆 ID，沒有展示另一欄多出的 UMC_2023_total_assets；第二次修訂仍保留多餘 ID。</p><p>建議下一步只改善 EVID-01 錯誤診斷：列出兩欄 ID、各自多出／缺少／重複的項目，讓模型依原題修正，維持原判定標準與重試上限。再用同一起點做小型對照確認；本輪尚未修改或驗證這項改善。</p><h2>如何判定修好</h2><p>先用既有 D runner 跑 validators 與獨立 context Judge；再離線比較原始已檢查 Dev 案例的答案、單位、evidence 集合與題型，並由 AI 檢查最終 semantic_parse 及 Python 是否真正符合原題。原始參考標註及正確性標籤沒有送入 Generator 或 Judge。Gate 接受本身不等於正確。</p><div class="note">這是 9 個 AI 合成錯誤的元件修復診斷，不是新的 A/B/C/D 主實驗準確率。起點是注入的錯誤初稿與可見 facts，並未重建原本完整 Generator 對話；9 個案例源自 7 道 Dev 題。候選資料已包含所需正確 facts，本輪 0 次新搜尋工具呼叫，因此測的是選用與修訂能力，並未驗證缺少必要 facts 時的檢索回復。標籤與語意檢查由 AI 完成，未經獨立人工審查。</div><h2>逐次輸入／輸出檢查</h2>'''+details+'''<h2>研究邊界</h2><p>本輪只有 Gemma，沒有追加 Qwen；未更改核心 runner、prompt、validators、Gold 或 A/B/C/D，未執行 Test 或自動 freeze。原先發現的回饋文字瑕疵仍需保留記錄，不能因本輪修復成功就宣稱其沒有風險。此診斷只測原本 C 可通過的 9 個案例，因此不包含 C 已攔截的 3 個 Context 缺失案例。</p></html>'''
    (OUT/'report.html').write_text(page,encoding='utf-8')
    print({k:v for k,v in report.items() if k not in ('cases','artifact_hashes')})

if __name__=='__main__':main()
