"""Readable, evidence-linked analysis of the completed Dev Judge diagnostic."""
import html
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from financial_annotation_harness.io_utils import read_json,read_jsonl,write_new_json,file_hash
OUT=ROOT/'outputs/dev-judge-diagnostic-v1'

def main():
    summary=read_json(OUT/'summary.json'); manifest=read_json(OUT/'manifest.json')
    rows=read_jsonl(OUT/'results.jsonl')
    names={k:v['model']['judge_model'] for k,v in manifest['settings'].items()}
    notes=[
      {'model':'model_2','case':'LG03__wrong_constraint','finding':'漏判量詞錯誤','detail':'將逐年下降所需的 AND 改成 OR，semantic_parse.logic 也改成任一相鄰年度下降。此資料剛好兩個年度皆下降，所以答案仍為 Yes；Qwen 四項均判 PASS。這是答案相同但推理不等價的具體漏判。'},
      {'model':'model_1','case':'SF09__wrong_concept','finding':'拒絕正確，但修正文字污染','detail':'同一回應第一項修正正確，第二項卻提出「其他綜合損益（104）」；104 並非所需概念名稱。不能因 overall_pass=false 就認定回饋完全可靠。'},
      {'model':'model_2','case':'AR07__missing_context','finding':'建議格式與共同 contract 不相容','detail':'建議把 selected_financial_facts JSON 放入 Context。現有 EvidenceValidator 需要 Markdown financial table，照做可能造成下一次仍被 C 擋下。Judge rubric 未完整帶入此格式約束，是待檢驗的介面資訊不足假說。'},
      {'model':'model_2','case':'AR09__missing_context','finding':'修正欄位與格式不精確','detail':'建議文字使用不存在的 golden_content 欄名，並要求 JSON 格式；目前欄名為 golden_context，且共同 contract 是 Markdown table。'},
      {'model':'model_2','case':'RT07__missing_context','finding':'ID 引用可能不足以修好 Context','detail':'回饋允許以 retrieved_fact_ids 引用補足 Context；僅列 ID 不足以滿足現行表格中的概念、年份與數值要求。'},
      {'model':'model_2','case':'GR03__wrong_evidence','finding':'總拒絕與子項判定不一致','detail':'回饋正確指出把資產換成負債，但 concept_pass 仍為 true。另 SF06/SF09 wrong_evidence 也有同型情況。整體拒絕可用，子項 failure analysis 應審慎解讀。'},
      {'model':'model_1','case':'CP03__wrong_constraint','finding':'是否能帶動完整修復尚未測試','detail':'回饋主要要求改 semantic_parse.logic，但該案例連 Python 與答案都改成最低值。尚未執行 Generator retry，無法宣稱能同步修復三者。CP05 與部分錯誤 evidence 亦應做小型端到端回復驗證。'},
    ]
    for note in notes:
        p=OUT/note['model']/(note['case']+'.json')
        note['response_path']=str(p.relative_to(ROOT));note['response_sha256']=file_hash(p)
        note['authority']='AI qualitative inspection; no human review; no verdicts altered'
    analysis={'observations':notes,'result':'Keep current Gemma Generator/Judge for now; no evidence here requiring prompt expansion or replacing Judge.',
      'recommended_next_step':'Bounded diagnostic feedback-retry test of the 9 C-passing errors using the current two-retry budget; measure actual recovery and regression before any core change.',
      'limitations':['12 original Dev questions, 24 correlated cases; deliberately selected faults, not natural error prevalence',
       'AI-authored expected labels; controls previously AI/formula checked, not independently human adjudicated',
       'One request per model/case; shared explicit parameters, native templates/defaults differ; fixed model execution order',
       'This tests Judge decisions, not Generator recovery, D main accuracy, or unbiased generalization',
       'Historical 48-question Test has been used; later runs are regression/version comparison, not pristine holdout'],
      'source_hashes':{p.name:file_hash(p) for p in [OUT/'manifest.json',OUT/'cases.jsonl',OUT/'results.jsonl',OUT/'summary.json']}}
    write_new_json(OUT/'qualitative_analysis.json',analysis)
    def rate(v):return f"{v['numerator']}/{v['denominator']}（{v['rate']:.1%}）" if v['rate'] is not None else '—'
    table=''
    for k,v in summary['by_model'].items():
        table+=f"<tr><th>{names[k]}</th><td>{rate(v['incremental_detection'])}</td><td>{rate(v['false_rejection'])}</td><td>{v['mean_latency_ms']/1000:.2f} 秒</td><td>{v['errors']}</td></tr>"
    categories=''
    for cat,label in [('wrong_concept','語意解析概念錯誤'),('wrong_constraint','最高／最低、AND／OR 約束錯誤'),('wrong_evidence','一致但答非所問的 evidence')]:
        categories+='<tr><th>'+label+'</th>'+''.join('<td>'+rate(summary['by_category'][m][cat]['incremental_detection'])+'</td>' for m in names)+'</tr>'
    cards=''
    for n in notes:
        relative=n['model']+'/'+n['case']+'.json'
        cards+='<article><h3>'+html.escape(names[n['model']]+'：'+n['finding'])+'</h3><p>'+html.escape(n['detail'])+'</p><a href="'+relative+'">'+html.escape(n['case'])+' 原始回應</a></article>'
    page='''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>Judge 診斷結論</title><style>body{font:17px/1.8 Microsoft JhengHei,sans-serif;max-width:1120px;margin:30px auto;padding:20px;background:#f4f7fb;color:#19314b}h1{line-height:1.4}article,.lead{padding:20px;background:white;border-radius:10px;margin:16px 0}table{width:100%;border-collapse:collapse;background:white}th,td{border:1px solid #ccd;padding:12px}a{color:#145caa}.note{border-left:5px solid #d8a342;padding:12px 20px;background:#fff5df}</style><h1>Gemma 能抓到 C 漏掉的錯誤；下一個缺口是回饋能否修好</h1><div class="lead">48/48 次本地 Judge 請求完成。這輪沒有修改 prompt、validators、A/B/C/D 或 Gold，也沒有執行 Generator、Test 或 freeze。<br><a href="report.html">查看全部 24 個案例 × 2 模型輸入／回應</a> · <a href="results.csv">下載逐筆 CSV</a> · <a href="qualitative_analysis.json">分析與來源雜湊</a></div><h2>Judge 決策結果</h2><table><tr><th>模型</th><th>C 通過錯誤的攔截率</th><th>正確案例誤拒率</th><th>本輪平均請求耗時</th><th>推論／解析失敗</th></tr>'''+table+'''</table><p>12 個正確案例、9 個 C 無法攔截的錯誤、3 個 C 已攔截的 Context 缺失案例。後三個兩模型皆判拒絕，另列，不灌入增量攔截率。速度含載入成本且未交錯執行，只供本輪成本參考。</p><table><tr><th>錯誤類型</th>'''+''.join('<th>'+n+'</th>' for n in names.values())+'</tr>'+categories+'''</table><div class="note">上述 100% 是 9 個合成錯誤的 Judge 攔截率，不是新的主實驗 E2E Accuracy。小樣本、同題變異、AI 標籤，不能宣稱 D 在一般題目必定優於 C。</div><h2>逐筆回饋品質檢查</h2>'''+cards+'''<h2>研究解讀與下一步</h2><p>現有 Gemma 在這批案例有語意攔截能力，因此目前沒有充分理由換模型或繼續疊加 prompt。先前 C/D 同分可與「自然 Dev 剩餘錯誤未觸發 Judge 增量」相容，但這輪不能證明唯一原因。</p><p>建議下一步只針對這 9 個通過 C 的錯誤，執行小型 feedback → Generator retry → validators → Judge 診斷，保留最多兩次 retry。量測真正修復率、只改文字未改 Python 的比例，以及回饋是否引入新錯誤。這一步尚未執行，不把本輪拒絕率當成 recovery rate。</p><p>凍結版本前先完成上述修復鏈確認。舊 48 題 Test 已使用，之後只能如實稱為版本回歸比較；要主張未見資料泛化需另建 holdout。</p><p>標籤與文字檢查由 AI 完成，沒有宣稱人工審查。Gold SHA256：'''+manifest['source_sha256']+'</p></html>'
    (OUT/'findings.html').write_text(page,encoding='utf-8')
    # Use real model names in the diagnostic viewer; leave immutable raw records intact.
    p=OUT/'report.html';s=p.read_text(encoding='utf-8')
    for k,n in names.items():s=s.replace(k,n)
    p.write_text(s,encoding='utf-8')
    print('Analysis written:',OUT/'findings.html')

if __name__=='__main__': main()
