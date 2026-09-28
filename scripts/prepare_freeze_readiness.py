"""Read-only study audit plus a versioned candidate snapshot; does not freeze/run models."""
import html,json,subprocess,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from financial_annotation_harness.io_utils import read_json,read_jsonl,file_hash,digest,write_new_json,timestamp
from financial_annotation_harness.governance import project_hashes
OUT=ROOT/'outputs/freeze-readiness-20260917'

def main():
    OUT.mkdir(exist_ok=False)
    dev=ROOT/'outputs/dev-prompt-v4/full-dev-v4'
    latest=ROOT/'outputs/dev-feedback-retry-v2'
    dm=read_json(dev/'manifest.json');lm=read_json(latest/'manifest.json')
    old=read_json(ROOT/'artifacts/freeze_manifest.json')
    core=project_hashes(ROOT);assert core==lm['project_hashes']
    gold=ROOT/'data/financial_qa_gold_dataset_v2.xlsx';gold_hash=file_hash(gold)
    assert gold_hash==lm['source_sha256']
    settings=dm['settings'];assert settings['model']==lm['settings']['model']
    assert dm['resolved_prompts']==lm['prompts']
    tracked=[]
    for folder in ('src','scripts','tests','config','prompts','docs','experiments'):
        tracked.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.json','.yaml','.md') and '__pycache__' not in p.parts)
    tracked.extend(ROOT/n for n in ('pyproject.toml','requirements.lock','README.md','artifacts/dataset_split.json'))
    hashes={p.relative_to(ROOT).as_posix():file_hash(p) for p in sorted(set(tracked))}
    sources={
      'dev':dev/'final-report/summary.json',
      'per_type':dev/'by-type/per_type.json',
      'judge':ROOT/'outputs/dev-judge-diagnostic-v1/summary.json',
      'retry_v1':ROOT/'outputs/dev-feedback-retry-v1/final_analysis.json',
      'retry_v2':latest/'comparison.json',
      'predicate':latest/'predicate_regression.json',
      'paired_inputs':latest/'paired_input_verification.json',
      'environment':dev/'runtime.json'}
    ledger={k:{'path':str(p.relative_to(ROOT)),'sha256':file_hash(p),'data':read_json(p)} for k,p in sources.items()}
    settings_record={'status':'CANDIDATE_NOT_FROZEN','settings':settings,'resolved_prompts':dm['resolved_prompts'],
       'role_overrides':dm['role_overrides'],'source_manifest':str((dev/'manifest.json').relative_to(ROOT)),
       'note':'Main Dev config call budget retained; diagnostic 270-call budget is not adopted as main experiment config.'}
    write_new_json(OUT/'candidate_settings.json',settings_record)
    write_new_json(OUT/'experiment_ledger.json',ledger)
    changed=[p for p in sorted(set(core)|set(old['project_hashes'])) if core.get(p)!=old['project_hashes'].get(p)]
    manifest={'status':'PREPARED_NOT_FROZEN','created_at':timestamp(),'source_sha256':gold_hash,
       'core_hashes':core,'source_snapshot_hashes':hashes,'old_freeze_sha256':file_hash(ROOT/'artifacts/freeze_manifest.json'),
       'old_freeze_changed_paths':changed,'candidate_settings_sha256':file_hash(OUT/'candidate_settings.json'),
       'git_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
       'git_status':subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True,encoding='utf-8'),
       'provenance_policy':'Snapshot hashes identify current uncommitted working state; git HEAD alone does not identify this candidate.',
       'review_mode':'ai_assisted','human_review_completed':False,'historical_test_already_used':True,
       'pending_before_freeze':['Versioned run entrypoint must use saved resolved prompts and role schemas exactly.',
         'Create a separate freeze manifest covering scripts, JSON configs and resolved prompts; retain historical freeze.',
         'Validate prepared run schedule/output isolation without model calls; later 48-question runs must be named regression/version comparison.'],
       'no_new_model_calls':True,'no_test_execution':True,'freeze_created':False}
    with zipfile.ZipFile(OUT/'candidate_source.zip','x',zipfile.ZIP_DEFLATED) as z:
        for path in hashes:z.write(ROOT/path,path)
    manifest['source_zip_sha256']=file_hash(OUT/'candidate_source.zip')
    write_new_json(OUT/'readiness.json',manifest)
    runtime=ledger['environment']['data'];hw=runtime['hardware'];model=settings['model']
    env={'GPU':hw['gpus'][0]['name'],'VRAM':str(hw['gpus'][0]['vram_mib'])+' MiB','RAM':str(round(hw['ram_bytes']/1024**3,2))+' GiB',
         'Ollama':model['expected_ollama_version'],'Generator / Judge':model['generator_model'],'Quantization':model['expected_quantization'],
         'Context':model['num_ctx'],'Temperature':model['generator_temperature'],'Repeat penalty':model['repeat_penalty'],
         'Max output tokens':model['max_tokens'],'Think':model['think'],'Model digest':model['generator_version']}
    table=''.join('<tr><th>'+html.escape(k)+'</th><td>'+html.escape(str(v))+'</td></tr>' for k,v in env.items())
    page='''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>凍結前版本整理</title><style>body{font:17px/1.8 Microsoft JhengHei,sans-serif;max-width:1100px;margin:30px auto;padding:20px;background:#f4f7fb;color:#19314b}section{background:white;padding:22px;margin:16px 0;border-radius:10px}table{width:100%;border-collapse:collapse}th,td{padding:10px;border:1px solid #ccd;overflow-wrap:anywhere}.notice{background:#fff3d8}a{color:#145caa}code{overflow-wrap:anywhere}</style><h1>研究候選版本：已整理，尚未凍結</h1><section><a href="candidate_source.zip">下載程式／設定／測試快照</a> · <a href="candidate_settings.json">完整候選設定與實際 prompt</a> · <a href="experiment_ledger.json">實驗紀錄索引</a> · <a href="readiness.json">版本雜湊與待辦</a><p>快照保存目前未提交的工作目錄內容；不是新 Git commit，也不是正式 freeze。Gold Excel 不在壓縮檔內，保留原檔並以 SHA256 識別。模型權重、全部原始 traces 及套件環境不包含在程式快照中；原始實驗仍保留於專案 outputs。</p></section><section><h2>已完成的證據</h2><ul><li><a href="../dev-prompt-v4/full-dev-v4/final-report/report.html">完整 Dev v4：12 題 × A/B/C/D × 3 次</a>；<a href="../dev-prompt-v4/full-dev-v4/by-type/report.html">六種題型結果</a>。此主實驗早於最新 EVID-01 回饋修改，不將其冒充最新版重跑。</li><li><a href="../dev-judge-diagnostic-v1/findings.html">Judge 診斷</a>：Gemma 攔截 9/9、Qwen 8/9，正確案例誤拒皆 0/12；保留 Qwen 作補充資料，暫停追加實驗。</li><li><a href="../dev-feedback-retry-v2/report.html">修復對照</a>：8/9 → 9/9，零退步；另外8個原始輸出完全相同，GR03只移除多餘ID。</li><li>最近一輪離線測試207項通過；舊19份標註通過／失敗判定不變。測試數是本次對話前一輪已執行的結果，本整理步驟沒有重跑測試。</li></ul></section><section class="notice"><h2>凍結前尚須完成</h2><ol><li>固定正式執行入口：目前一般 CLI 直接讀基礎 prompts；Dev runner 另組合 workflow/Judge 指引及 schema。必須使用本包保存的完整 resolved prompts 與 role overrides，先做不呼叫模型的執行計畫檢查。</li><li>建立獨立的新 freeze 紀錄：既有 artifacts/freeze_manifest.json 屬於舊版本，現有程式已不同。舊 project_hashes 不涵蓋全部 scripts 與 JSON config，本包額外補齊雜湊；正式凍結需一併驗證。</li><li>下一輪48題如要執行，明確命名為版本回歸比較。歷史 Test 已被使用，不能宣稱是未見 holdout；若需泛化結論，須另外建立未用資料。</li></ol><p>本次未執行 Test、未建立新 freeze，也未覆寫舊 freeze；不以AI檢查冒稱人工審查。</p></section><section><h2>實驗環境與固定設定</h2><p>硬體沿用 Dev v4 執行時的實測記錄；本次沒有重新查詢 runtime 或啟動模型。</p><table>'''+table+'''</table><p>A/B/C/D 使用同一 Generator；D Judge 使用相同模型、獨立 request/context。最多兩次 retry，不新增模型或擴充架構。</p></section><section><h2>論文呈現限制</h2><p>Dev 每題三次輸出高度重複，不能視為三倍獨立樣本；合成錯誤診斷與主實驗準確率必須分開。AI 審查未經獨立人工裁決。C/D 在 Dev 同分不表示 Judge 無效，也不能用合成案例9/9宣稱D在一般資料必定最好。</p><p>Gold SHA256：<code>'''+gold_hash+'</code></p></section></html>'
    (OUT/'report.html').write_text(page,encoding='utf-8')
    assert file_hash(gold)==gold_hash
    assert file_hash(ROOT/'artifacts/freeze_manifest.json')==manifest['old_freeze_sha256']
    assert all(file_hash(ROOT/p)==h for p,h in hashes.items())
    print(json.dumps({'status':manifest['status'],'snapshot_files':len(hashes),'old_freeze_changed_files':len(changed),'new_model_calls':0}))

if __name__=='__main__':main()
