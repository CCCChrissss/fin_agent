# 財務問答標註 Agent — Codex Handoff

> **最新狀態（2026-09-16 21:28 台北）：研究者已授權 AI 代審及自主執行。Gold 60 題 AI 審查與 Python/context 核對完成，非人工審查。`results/dev-ai-assisted-001` 正在執行 144 題次；`scripts/complete_ai_study.py` 已以背景程序接續等待，之後會自動離線 AI 評分、freeze、576 題次 Test 與評分。不要另開重複 runner、不要修改已被 manifest hash 固定的 src/prompts/config YAML/protocol。最新階段見 `outputs/ai-assisted-study/status.json`，視覺報告為 `outputs/ai-assisted-study/experiment_results.html`。本段取代下列歷史「等待人工」描述。**

本輪設定：`config/experiment.ai-assisted.v1.json`；Gold 審查紀錄：`artifacts/runtime/ai-gold-review-20260916.json`；方法修訂：`docs/ai_review_amendment.md`。主實驗仍固定 Gemma4 12B，A/B/C/D 不變。離線 AI reviewer 使用獨立 request、不看線上 Judge verdict/Generator history/Gold answer/Python result；同模型偏差須揭露。保存原人工審核工作簿未完成，不冒名填寫。

背景流程若報錯，讀 `outputs/ai-assisted-study/error.txt` 與 `commands.log` 後診斷，不可為成功率而重抽失敗題。Dev 完整後的自動 gate 僅查完整性與基礎設施錯誤，不以較高 accuracy 挑選 run。未定語意指標維持 null；不偽造人工labels。

> **2026-09-16 更新：E2E 根因分析、等價格式 parser v1.1 與兩模型共同離線重評已完成。研究者已選定 Gemma、省略 tie-break。人工審核已改成可操作的 Excel，並新增自動 validation 與離線 Dev preflight；下一步只需完成 [人工審查](review_gate_v1.1.md)。**
>
> 本文件依本機 repository、immutable results、review labels 與原始碼實際盤點建立，不是對話摘要。盤點基準 commit：`061700fc16f7b78cbbbd348c36b0b6c43ee0e116`。此為原交接基準；2026-09-16 已追加診斷及核准的格式修正／重評，沒有重新生成模型輸出。

## 1. 專案目的

研究者最新研究方向：**「具驗證與回饋機制之財務問答標註 Agent 設計與評估」**，預計投稿 TANET 2026。既有 README 的早期暫定題名仍屬研究歷史；本次沒有改寫 protocol。

工作目錄：`.`。GitHub：<https://github.com/CCCChrissss/fin_agent>。分支 `main`，遠端 `origin` 為該 repository。

系統產生可追溯的 annotation：問題語意分解 → 財務概念對應 → Financial Fact Search → evidence selection → Golden Context → Python reasoning → answer。C/D 再加入驗證、回饋與完成條件。研究核心是固定資料及模型下的 Harness 比較，不是完整財報 RAG 或多代理平台。

## 2. 研究問題

以 [experiment_protocol.md](experiment_protocol.md) 為準：

- RQ1：Structured Workflow 對第一次標註品質的影響。
- RQ2：Deterministic Validators 與 Feedback Retry 能否降低可程式判定的錯誤。
- RQ3：獨立 Semantic Judge 與 Completion Gate 的額外效果。
- RQ4（次要）：辨識簡明財報不足以回答的 Out-of-Scope 問題，降低 unsupported answer。

目前只完成模型 screening，尚未取得正式 A/B/C/D 主實驗成效。OOS 題庫／完整生成流程尚未完成；現有獨立 scope evaluator 不能代表該實驗已完成。

## 3. A/B/C/D 實驗架構

| Condition | 生成／Harness 元件 | Retry / Judge |
|---|---|---|
| A | Unguided LLM Baseline，共同 schema、question、fact tool | 無外部驗證回饋、無 Judge、無 retry |
| B | A + Structured Workflow | 首次最終輸出封存，無外部 validator 修正、無 Judge |
| C | B + 八項 deterministic validators + structured feedback | 初次一次，最多兩次 retry；無 Judge |
| D | C + independent Semantic Judge + Completion Gate | **共享**最多三個 attempts，不另增加 Judge retry 配額 |

四組共同 Generator、版本、量化、context、生成參數、facts/search、輸出 schema、unit rules、Gold。D 不使用更強 Generator。

八項 validator：SchemaValidator、FactExistenceValidator、YearValidator、UnitValidator、EvidenceValidator、PythonSyntaxValidator、PythonResultValidator、QuestionTypeValidator。

正式 Generator/Judge 之後採同一 tag/digest/quantization；Judge 只看 Original Question、Generated Structured Artifact、候選／選用 facts、rubric。禁止 Generator history、hidden reasoning、Gold Answer、Gold labels、Gold Python result 進入 Judge。

實作入口為 `runner.py::AnnotationRunner.run_question`。A/B 首個非工具回應即封存，malformed 亦保留；C/D 共用 retry budget。單一 attempt 可有多次 tool/model interaction，不等於 retry。D 只有全部 deterministic checks 與 semantic checks 通過才 ACCEPTED。

## 4. Dataset 與 Dev/Test

原始 Gold：`data/financial_qa_gold_dataset_v2.xlsx`，**read-only**。

- 60 questions、138 Financial Facts、60 Gold annotations、7 sheets。
- Single-Fact、Comparison、Growth_Rate、Ratio、Logic、Arithmetic，各 10 題。
- 固定 Development 12 題、Test 48 題，每類 Dev 2／Test 8。
- split：`artifacts/dataset_split.json`；algorithm=`sha256-canonical-json-v1`，seed=`20260915`。
- Dev ID：`AR07 AR09 CP03 CP05 GR03 GR06 LG01 LG03 RT04 RT07 SF06 SF09`。
- 原始 Excel SHA256：`9fea450f6937cc096f4f61dcf57be4901a139f9ba98588c3f2de2767aaa4a0ea`。

衍生目錄：`artifacts/derived/9fea450f6937cc096f4f61dcf57be4901a139f9ba98588c3f2de2767aaa4a0ea/`，含 `financial_facts.sqlite`、`question_inputs.jsonl`、`question_metadata.jsonl`、`gold_annotations.jsonl`、`audit.json`、`source_manifest.json`。本次唯讀 `verify_derived` 通過。Model input 使用 neutral question ID；Gold 題型前綴留於 metadata/trace，不送給模型。

已檢查 screening 的實際 IDs 全屬 Development，無 Test ID。研究者聲明 Test 尚未用於調整；本機可驗證的結果目錄也沒有正式 Test。**所有未留存於本 repository 的外部操作：尚未確認。**不可將本機紀錄不存在提升為對外部歷史的絕對證明。

## 5. Repository 結構

```text
data/                         原始 Excel，禁止覆寫
artifacts/dataset_split.json   受版控的固定 split
artifacts/derived/<hash>/      本機衍生資料，Git 忽略
artifacts/runtime/             本機稽核／測試暫存，Git 忽略
config/                       rules、aliases、設定範例；*.local.yaml Git 忽略
prompts/                      baseline、contract、workflow、judge_rubric
src/financial_annotation_harness/
  cli.py                      CLI 路由與資料／provenance 檢查
  dataset.py / facts.py        唯讀來源、衍生 SQLite、deterministic search
  schemas.py / config.py       共同契約與嚴格設定
  model_client.py             provider abstraction、OpenAI、scripted client
  ollama_provider.py          原生 Ollama adapter、版本驗證、參數紀錄
  runner.py / judge.py         A/B/C/D 流程與 fresh Judge context
  validators.py               deterministic checks
  python_executor.py          AST 限制、子程序、資源／逾時限制
  trace.py / io_utils.py       JSONL、hash、不可覆寫輸出
  screening.py                Dev-only B 排程、tie-break、resume
  evaluation.py              Gold-based component/E2E 評分
  screening_evaluation.py     screening 診斷、彙整、人工審查佇列
  governance.py               selection/freeze/provenance gate
  runtime_environment.py      Windows 環境快照
  smoke.py / demo.py           合成 smoke／離線軟體示範
tests/                        pytest、mock HTTP、synthetic fixtures
scripts/dev.ps1               repository 自有 PowerShell 入口
results/                      本機實驗，Git 忽略
```

**GitHub clone 不含 results、derived、local config 或 venv。**接手其他機器前需由研究者透過另行核准的管道提供既有結果及來源 snapshot，並核對第 17 節 hashes；不能 `git add -f results`，也不能重新生成模型回答代替缺失的 artifact。

本次 Git 初始狀態乾淨，無待整理的其他 tracked modifications；最近兩筆 commit：

- `061700fc16f7b78cbbbd348c36b0b6c43ee0e116`：Improve local model tool grounding and judge output。
- `abf9f56`：Initial commit: financial annotation harness。

## 6. 本地環境與固定模型版本

以下來自 screening-001 manifest／trace，**本次未重新查詢 Ollama 或啟動推論**。

| 項目 | 已記錄值 |
|---|---|
| Runtime | Ollama 0.33.3，`http://127.0.0.1:11434` |
| OS | Windows-11-10.0.26200-SP0 |
| GPU | NVIDIA GeForce RTX 5060 Ti |
| VRAM | 驅動回報 16,311 MiB |
| RAM | 33,454,280,704 bytes |
| GPU driver | 610.88 |
| Python | 專案要求 3.12；`.venv/Scripts/python.exe` |
| 套件 | `requirements.lock` 固定 hash |

| candidate_id | model_tag | quantization | digest |
|---|---|---|---|
| qwen35_9b | qwen3.5:9b | Q4_K_M | `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7` |
| gemma4_12b | gemma4:12b | Q4_K_M | `4eb23ef187e2c5462566d6a1d3bbbc2f1346d0b4327cbb66d58fffbcc9b2b05c` |

共同參數（manifest 與解析後 local config 相符）：num_ctx=8192；max_tokens/num_predict=4096；Generator/Judge temperature=0；supports_seed=true；base_seed=20260915；兩候選 think=false；structured_output_mode=prompt_only；concurrency=1；keep_alive=5m。top_p/top_k/repeat_penalty=null 代表未明確送出，不能宣稱兩模型的所有 runtime 預設相同。

connect timeout=5s；單次 request timeout=300s；question deadline=900s；max_wall_seconds=14400；max_tool_calls_per_attempt=12；max_model_calls_per_attempt=14；transport_retries=0；本次 screening local config 的 max_live_calls=400。warmup_requests=1／模型；unload_between_models=true。

Manifest `settings.model.generator_model=offline-scripted`、`generator_version=1` 是共用基底的預設值，**不是實際執行模型**。`ScreeningConfig.candidate_settings()` 以 candidates 覆寫；每題 attempts 的 model/model_version/runtime 才是實際候選身分。相同原因，嵌入 Settings 的 conditions=[A,B,C,D]、runs_per_condition=3、max_retries=2 不是 screening 排程：外層 condition=B、run_indices=[1] 才有效，trace 已驗證全部只有 attempt=1。

## 7. 已完成工作

- Python venv、鎖定依賴、唯讀匯入、SQLite facts、工具、validators、Judge、Retry/Gate、Trace、evaluation、freeze gate 已實作。
- Ollama preflight、digest/quantization 設定完成，已執行兩次真實合成 smoke。
- 兩候選 B screening 完成，共24題次、24個 final。
- Initial evaluation 完成，pending_reviews=14。
- 14 筆人工語意 review 已填入 labels；reviewed evaluation 完成，pending_reviews=0。
- 評估 summary 的 winner 仍為 null、原 selection_template 維持 DRAFT；這是自動評估的原始產物，不回填。2026-09-16 研究者另行確認 Gemma，正式 record 已建立於 config/model_selection/gemma4-12b-v1.json；尚無 freeze_manifest 或正式 Test。
- 本次只核對、寫 handoff、執行離線測試及 Git 操作；不更動既有實驗結果。

既有108項測試通過紀錄屬過去版本驗證；本次新執行結果另記於第17節，不能用歷史測試代替當次驗證。

## 8. Smoke 修正歷史

### smoke-live-001：30 次推論 request

來源：`results/smoke-live-001/smoke_report.json` 與各候選 events/attempts。

- Qwen 兩個合成案例 FAILED；包含反覆 tool calling／tool budget 耗盡。查詢格式混用年份與概念的問題是此次修正背景。
- Gemma 兩個案例 SUBMITTED、schema可解析、Python可執行，但 retrieval_observed=false，出現不存在的 evidence／fact ID。
- Qwen Judge schema_pass=true，但 used_fixture=true；Gemma Judge schema_pass=false、ValidationError。不能宣稱第一次兩個 Judge 都失敗。

### 共用修正：commit 061700f

Git diff 確認該 commit 修改三檔，非模型專屬 prompt：

1. `runner.py::search_tool_schema()`：query只放會計概念、年份放 years；已取得必要 facts 後停止搜尋。
2. `prompts/contract.md`：fact_id、數值、來源 unit、evidence 必須來自工具；資料不足 answer=null，不得虛構。
3. `prompts/judge_rubric.md`：observed_value 限簡短文字/scalar，避免嵌入大型 JSON/array/Markdown；明確要求合法 JSON。

### smoke-live-002：20 次推論 request

來源：`results/smoke-live-002/smoke_report.json`。

四個 Generator 合成案例均 SUBMITTED、schema_pass=true、retrieval_observed=true、Python success=true；兩個 Judge schema_pass=true、used_fixture=false。

**仍非全部 validator PASS。**報告保留 UNIT-05、POT-01，個別題有 GOLD-01／TIME-02。這次 smoke 證明基本執行鏈可以運作，不是完整 annotation 正確性證明，更不能拿來排名。

## 9. Screening 設計

`results/screening-001/manifest.json`：experiment_kind=screening、stage=initial、partition=development、condition=B、run_indices=[1]、兩候選。

12 Dev × 2 models × 1 run = **24 question-runs**。每模型實際題目順序：CP03、GR06、RT07、AR09、LG01、CP05、LG03、SF06、SF09、AR07、GR03、RT04。無 Test ID。

禁止 Test split、C/D、線上 validators/Judge 修錯、retry、模型專屬 JSON grammar。已讀24筆 attempts，皆 condition=B、attempt=1、validator_results={}、judge_result=null；沒有 Judge request events。

只有研究者判斷兩者品質真的接近時才決定 tie-break：run_indices=[2,3]，12 × 2 × 2 = 追加48題次。不能因兩個 E2E 同為0就自動觸發，其他品質／失敗指標差距仍須考量。

## 10. Screening 執行結果

來源：`evaluation-reviewed/summary.json`，並與 `model_comparison.csv`、24筆 `per_question.jsonl` 核對。比率以小數列示，表中截取六位；完整精度以 JSON 為準。

| 指標 | Gemma4 12B | Qwen3.5 9B |
|---|---:|---:|
| question_count / run_count | 12 / 1 | 12 / 1 |
| E2E accuracy | 0 | 0 |
| schema success | 1.000000 | 0.166667 |
| JSON parse success | 1.000000 | 0.166667 |
| Evidence macro P / R / F1 | 0.916667 / 0.916667 / 0.916667 | 0.166667 / 0.166667 / 0.166667 |
| Evidence micro P / R / F1 | 0.92 / 0.92 / 0.92 | 1.0 / 0.08 / 0.148148 |
| Python execution | 0.916667 | 0.166667 |
| Answer accuracy | 0.5 | 0.166667 |
| Financial Fact Retrieval Success | 0.833333 | 0.25 |
| candidate recall | 0.916667 | 0.25 |
| nonempty retrieval | 1.0 | 0.25 |
| inference_failure_count | 0 | 10 |
| no_output_count | 0 | 10 |
| timeout_count | 0 | 0 |
| unparseable_output_count | 0 | 0 |
| Generator request_count | 34 | 117 |
| tool execution success | 1.0 | 0.992126 |
| mean latency ms（含失敗題） | 16596.416667 | 15623.666667 |
| mean submitted latency ms | 16596.416667 | 11445.5 |
| pending reviews | 0 | 0 |
| E2E sample SD | null（僅一次run） | null（僅一次run） |

總推論153次 = 34 + 117 + 2次warm-up。根層 journal 有兩個 candidate_complete 與兩個 unload_complete。兩候選各12 attempts／12 finals，final linkage與JSONL record hashes通過核對。

Qwen 10筆 FAILED 的 infrastructure_error 全為 `RuntimeError: Tool call budget exceeded`，不是10次timeout；其他2筆 SUBMITTED。Gemma 12筆全 SUBMITTED。Qwen 沒有 final output 的10筆計 no_output，不計「有輸出但 JSON 無法 parse」，因此 unparseable_output_count=0 不代表輸出穩定。

Evidence P/R/F1僅比較ID集合，不等於 evidence_accuracy。Financial Fact Retrieval Success 指累積工具 candidates 包含全部 Gold required facts，與最終選用 evidence 不同。FAILED 保留於12題分母；速度均值不可脫離完成率單獨比較。

## 11. Human Review

`results/screening-001/review-labels.jsonl` 有14筆，reviewer欄全部為 **曾子桐**。這是檔案中署名；實際審查程序依研究者提供的說明，不以軟體 hash 證明人工身分或獨立性。

14筆來源為Gemma12筆＋Qwen2筆有效schema產物；Qwen另外10筆無artifact，不需要人工補填為正確。Initial queue有14筆，reviewed queue為空；全部review_id/artifact_hash應對應原產物，不能手動替換。

| 人工欄位 | 僅判斷的語意內容 |
|---|---|
| time_pass | 是否正確理解題目期間／年度 |
| concept_pass | 財務概念是否正確或語意等價 |
| filter_pass | 額外限制是否保留 |
| logic_pass | comparison、maximum、成長率、AND/OR等題意是否完整 |
| evidence_relevance_pass | evidence是否對應原題所需資料 |
| golden_context_sufficiency_pass | context是否足以獨立回答原題 |
| python_reasoning_pass | 公式／推理是否符合題意 |

unit格式、exact answer mismatch、schema、fact ID存在、Python執行由deterministic evaluator處理，不在human欄重複扣分。例：114／113年度應對應2025／2024；整體錯用2024／2023即使bool答案碰巧相同，Time/Evidence仍錯，但正確的成長率公式可獨立判reasoning=true。這些評分原則來自研究者；具體題目應用是否一致仍由下個任務核對，不重寫既有labels。

## 12. Current Blocking Issue

**根因分析已完成；詳見 [e2e_failure_analysis.md](e2e_failure_analysis.md)。目前 pending_reviews=0，研究者已選定 Gemma、省略 tie-break，正式 Test 未開始。**

2026-09-16 先以原程式完整重現 24 題，逐題 dict 與原 reviewed 完全相等。確認 Gemma 全部 UNIT-05 來自隱含標籤限制，RT07 的表格邊界也被誤拒。研究者已核准接受等價格式；UnitValidator／EvidenceValidator v1.1、精確 revision 檢查及共同離線重評已完成。

新結果：`results/screening-001/evaluation-reviewed-v1.1/`。Gemma unit accuracy 0/12 → 8/12，Qwen 0/12 → 1/12；Gemma RT07 的 GOLD-01 消失。兩模型 E2E 仍為 0，Gemma evidence_accuracy／python_accuracy 仍為 0。原 manifest、outputs、labels、舊 evaluation 都保留。

已定位的剩餘問題：Gemma 11 題 scalar 搭配非空 index_key（POT-01）、7 題 duration 缺 period_start（TIME-02）、2 題年份偏移（TIME-01）、3 題答案與 Python 不一致（POT-02），另有實際題型、答案單位或 context 錯誤。不能自動修原 annotation 或為非零 E2E 關閉這些規則。

研究者已於 2026-09-16 確認 Gemma、省略 tie-break，selection record 與 experiment.gemma4.v1.json 已建立並通過載入／selection hash 驗證。下一步完成 [Gold／rules／rubric review](review_gate_v1.1.md)。已準備分開的 Dev 12 題與 Test 48 題人工 Gold 材料，尚未評分；軟體通過測試不等於完成人工 review／freeze。

## 13. 下一步 Checklist

- [x] 分析 evaluation-reviewed/per_question.jsonl。
- [x] 建立Gemma12題E2E failure breakdown，逐筆列出必要component與rule。
- [x] 完成 Dev 失敗根因與格式契約差異分析；完整 Gold／rules review 仍待研究者完成。
- [x] 依研究者確認，先加失敗測試再修等價格式 parser，保存原因與精確 code hashes。
- [x] 原始 immutable artifacts 共同重評至 evaluation-reviewed-v1.1，保留原生成與新評分版本。
- [x] 研究者確認省略 tie-break，不新增模型抽樣。
- [x] 研究者選定 Gemma，記錄品質、穩定性與速度取捨。
- [x] 建立正式 selection record，核對 tag/digest/quantization 及 reviewed evidence hash。
- [ ] 在 `financial_gold_review_v1.1.xlsx` 完成 Gold／deterministic rules／Judge rubric review，並取得 `validate-review=COMPLETE`、`dev-preflight=READY`。
- [ ] 同一Generator/Judge模型執行12 Dev的A/B/C/D。
- [ ] 僅利用Development做Harness tuning。
- [ ] Freeze v1.0。
- [ ] 經授權後執行48 Test × 4 × 3＝576題次。
- [ ] 主實驗metrics與failure analysis。

## 14. 不可以做的事

- 不修改原始Gold、固定split、已存在screening/評估/labels檔案。
- 不用Test調prompt/rules/Judge，不直接啟動正式48 Test。
- 不在screening後只為Qwen或Gemma提供特殊prompt、參數或強制JSON grammar。
- 不為迎合Gemma而放寬evaluator，不將所有E2E=0直接歸咎模型。
- 不把online Judge PASS當Gold，不把smoke當排名，不排除FAILED分母。
- 不變更已確認的 Gemma 選模／省略 tie-break 決定，也不宣稱研究實驗已完成。
- 不重新生成同一批Dev後挑最好輸出，不改hash以繞過provenance gate。
- 不下載／輪詢／監控模型來「等進度」；缺資料時先取得原artifact。
- 不新增OCR、Vector DB、XBRL crawler、Web frontend或不必要Multi-Agent。
- 不force-add被忽略的results、runtime、venv或local config進Git。

## 15. 常用命令

全部在 `.` 的PowerShell執行；需要Python3.12的`.venv`。命令名稱及旗標已對照`cli.py::parser`與`scripts/dev.ps1`。以下模型命令是操作參考，**不是交接後立即執行清單**。

### 接手第一個調查：唯讀已評分components

```powershell
Set-Location '.'
Get-Content -LiteralPath '.\results\screening-001\evaluation-reviewed\per_question.jsonl' -Encoding UTF8 |
    ForEach-Object { $_ | ConvertFrom-Json } |
    Where-Object candidate_id -eq 'gemma4_12b' |
    Select-Object question_id,semantic_parsing_accuracy,question_type_accuracy,evidence_accuracy,python_accuracy,answer_accuracy,unit_accuracy,e2e,offline_failure_codes |
    Format-Table -AutoSize
```

接著針對單題（例如RT07）讀完整 `offline_validator_results`，不要只看上述可能被表格截短的錯誤代碼：

```powershell
Get-Content -LiteralPath '.\results\screening-001\evaluation-reviewed\per_question.jsonl' -Encoding UTF8 |
    ForEach-Object { $_ | ConvertFrom-Json } |
    Where-Object { $_.candidate_id -eq 'gemma4_12b' -and $_.question_id -eq 'RT07' } |
    ConvertTo-Json -Depth 30
```

### 測試與離線規模確認

```powershell
git status --short --branch
git diff --check
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 test -q
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 screen --config config/screening.local.yaml --output results/screening-new --dry-run
```

dry-run只確認24題次，不開始推論。Tests阻擋網路，fixture輸出在artifacts/runtime新暫存目錄，不應修改既有results。

### 一次性preflight與smoke（只有重新驗證環境需求且獲授權時）

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 ollama-preflight --config config/screening.local.yaml --output artifacts/runtime/preflight-handoff-new.json
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 smoke --config config/screening.local.yaml --output results/smoke-new --dry-run
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 smoke --config config/screening.local.yaml --output results/smoke-new --live
```

`--live`會執行本機模型；不要重用已存在輸出目錄。不要週期性呼叫preflight。

### Screening／offline evaluation命令參考

```powershell
# 已完成的screening不得照此重新生成；只有明確核准的新研究批次才用--live。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 screen --config config/screening.local.yaml --output results/screening-new --live
# 不呼叫模型。僅在需要重新評估且provenance相符時使用新的輸出目錄。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 evaluate-screening --experiment results/screening-001 --reviews results/screening-001/review-labels.jsonl --revision config/evaluation_revisions/screening-001-format-v1.1.json --output results/screening-001/evaluation-reviewed-new
```

**Provenance 限制：**不指定 revision 時仍嚴格比較原始 source／split／project hashes。指定 revision 只允許 JSON 精確列出的評分檔案 before／after 差異，且 source／split 不得變動；prompt、rules、runner 等不在允許名單。新結果記錄 `evaluation_provenance.json` 與 summary 內的雙版本 hash，不編輯原 manifest。若之後程式再次變更，現有 revision 會失效，必須另建有原因及授權的新 revision，不能更新原 record 迎合新檔。

此核准流程已於 2026-09-16 實作；版本檔在 `config/evaluation_revisions/screening-001-format-v1.1.json`。Results 不納入 Git，跨機器交接須另移交資料。

## 16. 重要檔案位置

以下相對本專案根目錄，目錄與檔名已核實。

| 資料／用途 | 位置 |
|---|---|
| Gold原檔 | `data/financial_qa_gold_dataset_v2.xlsx` |
| 固定split | `artifacts/dataset_split.json` |
| 原始資料／衍生檔案hash | `artifacts/derived/<Excel SHA256>/source_manifest.json` |
| Facts、Gold副本、原題/metadata | 同上衍生目錄 |
| 實際screening設定（本機） | `config/screening.local.yaml` |
| 範例／正式未選定設定 | `config/screening.example.yaml`、`config/experiment.example.yaml` |
| 共用規則／別名 | `config/rules.yaml`、`config/concept_aliases.yaml` |
| Prompts | `prompts/contract.md`、`workflow.md`、`baseline.md`、`judge_rubric.md` |
| Smoke報告 | `results/smoke-live-001/smoke_report.json`、`results/smoke-live-002/smoke_report.json` |
| Screening manifest/lifecycle | `results/screening-001/manifest.json`、`events.jsonl` |
| Gemma原始紀錄 | `results/screening-001/gemma4_12b/run_01/B/{events,attempts,finals}.jsonl` |
| Qwen原始紀錄 | `results/screening-001/qwen35_9b/run_01/B/{events,attempts,finals}.jsonl` |
| Initial評估 | `results/screening-001/evaluation-initial/` |
| 人工labels | `results/screening-001/review-labels.jsonl` |
| Reviewed評估 | `results/screening-001/evaluation-reviewed/` |
| 關鍵評分檔 | reviewed目錄的 `summary.json`、`per_question.jsonl`、`model_comparison.csv`、`per_run.jsonl` |
| 未完成選模範本 | reviewed目錄的 `selection_template.json`（DRAFT） |
| 下任首讀原始碼 | `src/financial_annotation_harness/{screening_evaluation,evaluation,validators,runner}.py` |

README與local_model_screening內「尚未真實推論」等早期敘述，以本handoff的artifact盤點為最新狀態；本次不修改被manifest納入hash的研究文件。

## 17. Reproducibility / Provenance

**下列表格是原 screening／交接版本的歷史核對，並非現在程式 hash。**2026-09-16 修正後的精確差異在 revision JSON，新結果及其 hashes 見失敗分析報告。

本次核對：source/derived hashes有效；本機解析後local config等於screening manifest；所有manifest.project_hashes與目前相對檔案一致；兩候選attempts有相同prompt_version。基準commit `061700fc16f7b78cbbbd348c36b0b6c43ee0e116` 為盤點時HEAD；manifest本身沒有直接存Git SHA，對應關係以實際檔案hash驗證，不冒稱manifest有該欄。

Canonical hash定義：UTF-8 JSON、sort_keys=true、ensure_ascii=false、separators=(',',':')、allow_nan=false，再SHA256。它與原始檔案bytes的SHA256不同，**不可混用**。

| 追溯項目 | 已核對值 |
|---|---|
| manifest canonical hash | `5c9943cba09fe81d4c61569679c52620f9ff428b0fdcc2e10f60d289290f8b89` |
| manifest file SHA256 | `e91e430f5a48dae76fb198c075857905b0b1fa3a1a17efce1ac42b4bbc18b2d7` |
| reviewed review_labels_hash | `5bb9609b9e501cb04911bccf2f967db7d63c25fc35e15afed9d9797088d0f3ee` |
| review-labels.jsonl file SHA256 | `53019199e1f4f8ab77b8336db24c9a68f41c9ec50239e03182081c5884e5f1e6` |
| reviewed summary file SHA256 | `e2682b444c0c85a33da214329583fd34fe6bbdf70ba260e6cb8f82471e4fb756` |
| reviewed per_question file SHA256 | `4fc0a7c9a2e160837af4878253110007dc7d912a915ed1d8befa74dc74245b69` |
| source_manifest canonical hash | `7358bfe500820207e5cc75e412fb8c6a3ea7f24d59f1f37498bc4a39273303b0` |
| split canonical hash | `a77a1c4c448c7b377b09fdf0f7dd1f7a36b853ae7090eb5c87e4cdbf381bc2cf` |
| prompt_version（四份prompt字典） | `e2b7ca7891eb16460e0ea0bb8d392fb7b11b3c307a4b3955dbda2326f7e04fd9` |
| evaluation.py file SHA256 | `356699cd72d32bf37ea74f80f31bbc29906d9c4e7a3e2380bdef09cdcac40374` |
| screening_evaluation.py file SHA256 | `4b194e802fd86fa372a28b312a3660d560fbe0a2d0cb1783ad20891238360f2f` |
| validators.py file SHA256 | `ed779dfa98ebb8acfc301578b2f026158478139753ce9c3e853b443d483868b4` |
| rules.yaml file SHA256 | `60ca971129a847a33ce2f13a4bdaccdb65f44cb01aa5bc35e5f881203e707fa3` |

模型與Ollama版本見第6節；完整各檔project_hashes留在manifest，不只依賴上表節錄。不同checkout的CRLF/LF會影響file hash，若不符應查明換行／版本原因，不能更新manifest迎合新檔。

本handoff的Git commit可用 `git log -1 --format=%H -- docs/CODEX_HANDOFF.md` 取得，避免在文件內填寫不可能自我引用的commit SHA。

本次交付驗證（2026-09-15）：`git diff --check` 通過；`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 test -q` 結果為 **108 passed in 17.83s**，本次未出現歷史上的 `.pytest_cache` WinError 5 warning。交接前後比對既有 results、Gold、split、config、prompts、source、tests、scripts、derived 共 **95 個檔案**的 SHA256，沒有內容變更、新增或遺失。本次只新增 handoff 並更新 README，沒有重新呼叫模型或執行正式實驗。

## 18. 最後狀態摘要

> # CURRENT STATE
>
> - **Screening completed**：24 question-runs，153 inference requests（含2 warm-ups）。
> - **Human review completed**：14筆署名labels已匯入。
> - **pending_reviews = 0**。
> - **winner SELECTED: Gemma4 12B**；研究者確認，省略 tie-break。
> - **Formal Test NOT started**：本機無正式Test產出，與研究者聲明一致。
> - **E2E analysis and format-equivalence v1.1 reevaluation completed**：根因已定位，Gemma unit 8/12，E2E 仍為 0。
> - **Next task = human Gold/rules/rubric review**；材料已備妥，尚未核准。
> - **人工審查完成前不啟動 Dev A/B/C/D；Freeze 前不啟動正式 Test。**
