# Dev A/B/C/D 前的人工審查

2026-09-16：研究者已確認選用 **Gemma4 12B** 作 Generator 與 fresh-context Judge，**省略 tie-break**。此確認只完成選模，不代表已審核 Gold、deterministic rules 或 Judge rubric。

## 已完成與待完成

| 項目 | 狀態 | 證據／待辦 |
|---|---|---|
| Model screening | 完成 | 既有 24 題，兩候選 Condition B |
| Screening 人工 semantic labels | 完成 | 14 筆、pending_reviews=0；不同於整份 Gold 審查 |
| 格式解析修正及共同重評 | 完成 | evaluation-reviewed-v1.1，兩模型 E2E 仍為 0 |
| 正式選模 | SELECTED | config/model_selection/gemma4-12b-v1.json |
| Tie-break | 省略 | 研究者確認，schema／evidence／無輸出差距明顯 |
| Gold review | **PENDING** | 人工核對下列 Dev／Test 審查材料 |
| Deterministic rules review | **PENDING** | 核對下列驗證契約與適用範圍 |
| Semantic Judge rubric review | **PENDING** | 核對四項語意標準與 context 隔離 |
| Dev A/B/C/D | 未開始 | Dry-run 為 144 題次，推論預算 0 |
| Freeze／正式 Test | 未開始 | 不能用選模確認或軟體測試代替人工 attestation |

## 選模與固定設定

- Selection：`config/model_selection/gemma4-12b-v1.json`，授權來源記為本次 Codex 對話使用者；未冒用既有 labels 的審查者姓名。
- 可載入設定：`config/experiment.gemma4.v1.json`。沿用現有 loader，JSON mapping 已經實際載入驗證，不需要新增套件。
- Generator／Judge：`gemma4:12b`。
- Digest：`4eb23ef187e2c5462566d6a1d3bbbc2f1346d0b4327cbb66d58fffbcc9b2b05c`。
- Quantization：`Q4_K_M`；Ollama：`0.33.3`；num_ctx：8192；max_tokens：4096。
- Temperature：Generator／Judge 均 0；think=false；base_seed=20260915；structured_output_mode=prompt_only。
- 其餘 timeout、keep_alive、sampling 設定沿用 screening 中 Gemma 的 resolved_model_config，沒有替 D 使用更強模型。
- `max_live_calls=0`：此為審查前準備設定。完成審查後、執行前再明確設定整批推論預算；這不表示正式實驗已 freeze。

`validate_selection()` 已核對 selection 的 candidate、模型身分、summary hash 與 pending reviews，且 resolved settings 與保存內容一致。模型參數來自已封存 screening；本輪沒有呼叫 Ollama 確認當下 runtime，正式執行時仍須通過原有身分檢查。

## Gold 人工審查材料

主要審查介面改為 `outputs/01a0a120-5fa6-74f1-9ac9-d0cee8453df0/financial_gold_review_v1.1.xlsx`。工作簿整合 60 題 Gold、rules 與 Judge rubric，包含下拉選單、篩選、凍結窗格、進度公式及來源 hash。舊 Markdown 審查包仍保留於 `artifacts/runtime/human-review-v1.1-20260916/`，只作追溯。

- `gold-development.md`：12 題，逐題原文、Gold 語意、答案、來源 facts、期間、單位、來源 cell、context、Python。
- `gold-test.md`：48 題，同樣內容，只供人工 Gold 核對，**不得用來調整 prompt、rules 或 Judge**。
- `gold-development-labels.template.jsonl`／`gold-test-labels.template.jsonl`：逐題審查欄位，全部為 null，reviewer 為空。
- `manifest.json`：source SHA256、split hash、derived Gold hash、各審查材料 file hash，狀態為 PREPARED_NOT_REVIEWED。

本輪僅依固定 split 輸出人工閱讀材料，未讓模型回答 Test、未執行其中 Gold Python，也未自動替研究者判定任何題目正確。

每題請核對四項：

1. `question_and_semantics_pass`：問題與 Time／Concept／Filter／Logic 是否一致。
2. `source_facts_units_periods_pass`：來源值、正負號、單位與 instant／duration 期間是否正確。
3. `evidence_completeness_pass`：evidence 是否必要、完整，context 是否忠實呈現。
4. `python_formula_and_answer_pass`：Gold Python 公式、分子分母、年度次序、百分比尺度、rounding、答案是否正確。

在 Excel 的黃色欄位填寫 reviewer、四項逐題判定、rules 決定、Judge 決定與必要備註。不要改 Question_ID、partition、Gold_Record_Hash 或參考資料欄。這不是 screening 的七欄 semantic labels，不可傳給 `evaluate-screening --reviews`。

完成後執行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 validate-review --input outputs/01a0a120-5fa6-74f1-9ac9-d0cee8453df0/financial_gold_review_v1.1.xlsx --output artifacts/runtime/gold-review-validation.json
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 dev-preflight --config config/experiment.gemma4.v1.json --review-workbook outputs/01a0a120-5fa6-74f1-9ac9-d0cee8453df0/financial_gold_review_v1.1.xlsx --output artifacts/runtime/dev-preflight.json
```

`validate-review` 會核對 60 題是否齊全、hash/partition 是否未被改動、所有人工欄位是否完成，以及「不通過／需調整」是否有備註。`dev-preflight` 完全離線，不呼叫 Ollama；只有 review 狀態 COMPLETE 才會回報 READY。

發現錯誤時填 false 與具體原因，先討論處置。原 Excel 與既有 derived 不能原地修改；Test 題目的發現也不能拿來調整 Harness，應另行記錄 Gold 資料處置決定。

## Deterministic rules 審查清單

請讀 `config/rules.yaml`、`prompts/contract.md`、`src/financial_annotation_harness/validators.py` 及 `docs/evaluation_rubric.md`。以下是待確認內容，不是自動核准：

| 元件 | 需要確認的政策 |
|---|---|
| SchemaValidator | 四組同一 schema；型別、缺欄、多餘欄位不自動修復 |
| FactExistenceValidator | ID 必須存在且由本題工具取回，不能以模型記憶或 Gold 補值 |
| YearValidator | 明確年份需完整；duration 為全年起訖，instant 為年末且 start=null；錯年或漏日期不自動補正 |
| UnitValidator v1.1 | 來源值與答案的單位分開檢查；接受已核准等價標示，不接受錯單位、未知單位或相互衝突標示 |
| EvidenceValidator v1.1 | evidence/value/context 精確一致；scalar 的 index_key 必須為 null；dict 則給正確 key；operand 需參與 return 計算 |
| PythonSyntaxValidator | 唯一 solution()、受限 AST、有限 scalar、timeout 與記憶體限制，不擴充任意 Python 執行 |
| PythonRe sultValidator | 實際執行 result 等於 generated answer；執行成功不等於 Gold 正確 |
| QuestionTypeValidator | 主要運算與題型一致；Ratio／Growth 的尺度、順序與 round(...,2) 按共同契約 |
| Offline evaluation | 六元件 AND；FAILED 不排除分母；人工七項語意評分與 deterministic checks 各司其職 |

目前需明確理解的邊界：context 列名仍依 fact 的 concept_zh 精確比對，沒有新增概念同義詞；新增支援的無左邊界表格必須有匹配分隔列，舊 bordered-table 行為維持。這些限制不應因單一模型結果而偷偷改變。如要變更，需另列政策、測試與版本，不覆寫 screening-v1.1。

- [ ] 已審核以上政策及適用範圍，或逐項記錄不同意之處。
- [ ] 已確認 A/B 不使用 validators 修正輸出；C/D 才使用驗證及回饋，最多 2 次 retry。
- [ ] 已確認不把 answer 正確、Python 可執行、Evidence F1 高直接當作 E2E 正確。

## Semantic Judge rubric 審查清單

請讀 `prompts/judge_rubric.md` 及 `src/financial_annotation_harness/judge.py`。

- [ ] semantic_parse_pass：Time／Concept／Filter／Logic 保留題意，不增加不受支持維度。
- [ ] concept_pass：概念真正符合問題，不能因數值相同就視為等價。
- [ ] evidence_pass：選用資料相關，足以支援必要推理。
- [ ] golden_context_pass：context 能獨立支援全部必要推理，包括跨年及 AND／any／all。
- [ ] overall_pass 為四項 AND；FAIL 提供具體 field、observed、expected、correction；observed_value 不嵌入大型 JSON。
- [ ] 不重判 schema、ID 存在、Python 執行或 Python-result/answer equality。
- [ ] 每次 request 用 fresh context，只收到原題、structured artifact、候選／選用 facts 與 rubric；沒有 Generator 歷史、hidden reasoning 或 Gold。
- [ ] 同模型 Judge PASS 不作 Gold；最終正確性仍以獨立離線評估與人工 labels 為準。

`judge_messages()` 的 request 組裝已閱讀：建立新的 system/user 兩筆 messages，沒有接收歷史或 Gold 的參數。本輪沒有重新呼叫真實 Judge。

## 完成人工審查後的回覆方式

請提供實際審查者姓名，以及：

1. Gold：是否完成 60 題審查、已填 labels 複本位置、發現的問題。
2. Rules：同意現行 v1.1 政策，或列出需調整項目及原因。
3. Rubric：同意現行 Judge rubric，或列出需調整項目及原因。

選模紀錄中的 PENDING 是選模當時狀態；後續以新的審查完成紀錄追溯，不應回頭把最初 selection 當成人工核准所有資料的證據。

## 下一階段命令

以下 dry-run 已執行，結果為 12 × 4 × 3 = **144 question-runs**、0 live calls：

```powershell
# 在 . 執行
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 run --config config/experiment.gemma4.v1.json --partition development --output results/development-001 --dry-run
```

不要現在執行 --live 或 freeze。完成審查後才設定推論預算、再核對模型身分與 resolved config，執行 Dev A/B/C/D；Dev tuning 完成後才 Freeze v1.0，最後才跑 48 Test × 4 × 3。
