# Screening-001：Gemma E2E 0/12 原因分析

分析日期：2026-09-16。範圍只含既有 Development screening，兩模型各 12 題、Condition B、run 1。沒有重新生成回答，沒有讀取 Test 題目作為調整案例。研究者已確認接受等價格式；parser v1.1 與兩模型原始輸出的離線重評均已完成，結果見「v1.1 修正與重評」節。

## 結論與目前狀態

**原始 E2E 0/12 可由目前 evaluator 完整重現，但失敗原因同時包含模型的契約違反，以及驗證器未向模型明示的格式限制。不能把 E2E=0 解讀為 12 題財務推理全部錯誤，也不能把所有失敗當成 evaluator bug。**

- Gemma 12 題全部被 `UNIT-05` 擋下：context 都標了「單位：…」，程式只搜尋「來源單位：…」或 `Source unit:`。
- Gemma 11 題可執行程式全部出現 `POT-01`：annotation 把 scalar 變數搭配非空 `index_key`，驗證器依 dictionary 綁定解讀後找不到值。這是綁定契約錯誤，不是執行器漏掉 locals。
- 7 題 `TIME-02` 來自 duration 的 `period_start=null`，而對應資料明確為當年 01-01 起；2 題另有實際年度偏移。
- 7 題 `GOLD-01` 不能一概視為漏證據：其中 RT07 是資料完整但無最外側直線的 Markdown 表格，現有 parser 不支援；其他案例有純文字、缺分隔列，或表格概念名稱不完全相同等不同問題。
- 三題答案與其 Python 結果不一致；Comparison／Logic 的輸出單位也有混淆。
- 原始分數不覆寫；新結果另存 `evaluation-reviewed-v1.1`。研究者已選擇接受等價格式解析，共同適用於兩模型及 A/B/C/D；研究者後續已確認選用 Gemma，省略 tie-break；見 config/model_selection/gemma4-12b-v1.json。

## 資料與重現證據

修正前程式基準：`bda4a5d489dc51e28c8190f1a9f1019dc9642780`（交接文件提交）。本節的重現發生於修改程式前，當時 hash 與 screening manifest 一致。後續 v1.1 程式 hash 已不同，必須使用明確 revision 命令。

讀取來源：

- `results/screening-001/manifest.json`
- `results/screening-001/evaluation-reviewed/per_question.jsonl`
- `results/screening-001/evaluation-reviewed/summary.json`
- `results/screening-001/review-labels.jsonl`
- `results/screening-001/{gemma4_12b,qwen35_9b}/run_01/B/{attempts,events,finals}.jsonl`
- `artifacts/dataset_split.json` 與 hash 對應 derived 目錄；只以 Dev IDs 對照 Gold 與題目。

使用既有 CLI 在新目錄重評，保留原結果：

```powershell
# 在 . 執行；不呼叫 Ollama，不需要載入模型。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 evaluate-screening --experiment results/screening-001 --reviews results/screening-001/review-labels.jsonl --output artifacts/runtime/e2e-audit-20260916
```

本次成功輸出 24 題、pending_reviews=0；新舊 `per_question.jsonl` 解析後逐筆 dict **完全相等**，包括各 validator measurements。CLI 同時核對 source/code provenance、trace hash、terminal linkage、模型身分、Condition B 無 validator／Judge，以及人工 labels 對應。

重跑此命令須另用不存在的輸出目錄；既有目錄會被拒絕覆寫。此重現不等於證明評分政策合理，只證明原結果可重現。

## 六元件逐題 breakdown

E2E 的六元件是 Semantic Parse、Question Type、Evidence、Python、Answer、Unit。Schema 與 Python Execution 另報，不能誤稱第七個 E2E 元件。

下表分數直接來自原 reviewed 檔。`S/T/E/P/A/U` 為六元件；1=通過，0=失敗。規則以每題去重列出，沒有將同一題多個 issues 當成多題。

| 題目 | S | T | E | P | A | U | E2E | Python 執行 | Evidence F1 | Offline rule IDs |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| CP03 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 | GOLD-01, POT-EXEC, UNIT-02, UNIT-05 |
| GR06 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 1.00 | POT-01, GOLD-01, POT-02, UNIT-05, TIME-02 |
| RT07 | 1 | 1 | 0 | 0 | 1 | 0 | 0 | 1 | 1.00 | POT-01, GOLD-01, UNIT-05 |
| AR09 | 0 | 1 | 0 | 0 | 1 | 0 | 0 | 1 | 1.00 | POT-01, GOLD-01, UNIT-05, TIME-02 |
| LG01 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 1 | 0.50 | POT-01, TYPE-01, UNIT-02, UNIT-05, TIME-01, TIME-02 |
| CP05 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 1.00 | POT-01, GOLD-01, UNIT-02, UNIT-05 |
| LG03 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 1.00 | POT-01, UNIT-02, UNIT-05, TIME-02 |
| SF06 | 0 | 1 | 0 | 0 | 1 | 0 | 0 | 1 | 1.00 | POT-01, UNIT-05, TIME-02 |
| SF09 | 0 | 1 | 0 | 0 | 1 | 0 | 0 | 1 | 1.00 | POT-01, UNIT-05, TIME-02 |
| AR07 | 1 | 1 | 0 | 0 | 1 | 0 | 0 | 1 | 1.00 | POT-01, UNIT-05 |
| GR03 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 0.50 | POT-01, GOLD-01, POT-02, UNIT-05, TIME-01 |
| RT04 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 1.00 | POT-01, GOLD-01, POT-02, UNIT-05, TIME-02 |

Schema 12/12；S 2/12、T 11/12、E/P/U 各 0/12、A 6/12；Python execution 11/12。Evidence macro F1=11/12，與完整 evidence correctness 不同。

| Rule | 受影響題數 / 12 | 原因摘要 |
|---|---:|---|
| UNIT-05 | 12 | 單位標籤詞未被 parser 接受；RT07 另有 unit alias 問題 |
| POT-01 | 11 | scalar 卻填非空 index_key，共 22 個 bindings |
| GOLD-01 | 7 | context 格式或概念列不符合現有 parser |
| TIME-02 | 7 | duration 缺少 period_start，共 13 個 evidence-period issues |
| UNIT-02 | 4 | CP03、CP05、LG03 的答案單位錯；LG01 題型錯導致 expected unit 不同 |
| POT-02 | 3 | GR06、GR03、RT04 的 answer 與實際 Python result 不一致 |
| TIME-01 | 2 | LG01、GR03 使用 2023/2024，題目要求 2024/2025 |
| POT-EXEC | 1 | CP03 產生兩個 solution 函式，違反受限執行契約 |
| TYPE-01 | 1 | LG01 宣告 Comparison，程式實際是布林比較 |

## 原因一：UNIT-05 的隱含標籤限制

共同 `prompts/contract.md` 要求「末尾標示來源單位」，沒有要求逐字以「來源單位」作標籤。Gemma 11 題用了 `單位：TWD_thousand`，RT07 用 `單位：新台幣千元`。原程式 regex 只辨識 `來源單位`／`Source unit`，而 `UNIT_MAP` 也沒有 `新台幣千元` 這個 alias。

**最小診斷探針：**只在記憶體複本把標籤 `單位：` 改成 `來源單位：`，重跑 UnitValidator。11 題的 UNIT-05 消失；RT07 仍因 alias 未映射而失敗。四題 UNIT-02 照常保留。此探針未保存成模型回答、未用於新分數，也沒有修改原 annotation。

分類：**contract／parser 不一致，存在格式誤拒**。建議解析器接受明確且不矛盾的來源單位等價標示；錯誤單位、缺單位與相互衝突的標示仍應 FAIL。不能直接關閉 UNIT-05。

## 原因二：POT-01 是 binding 錯誤，不是 Python 無法執行

例如 AR07：

```python
total_assets = 578996009
total_liabilities = 199140569
result = total_assets - total_liabilities
```

annotation 卻宣告 `variable_name=total_assets, index_key=2025`。契約說明 dictionary 才以 index_key 指定年份，這裡 scalar 應為 null。驗證器先取得 scalar，再依非空 index_key 嘗試 dictionary lookup，得到無值，故 POT-01。

已用原始 execution.locals 核對：11 題可執行程式的 22 個 scalar 值都等於宣告 evidence.value。只在記憶體把這些 index_key 改成 null，全部 POT-01 消失；沒有改動 Python 或財務值。這證明原因是 binding 宣告，不是 locals capture 失效。

分類：**模型違反既有綁定契約**。不能在正式評分時忽略非空 index_key 或自動修 annotation。之後 Dev tuning 可在四組共同契約提供 scalar/null 與 dict/key 對照例；screening 原輸出保留。

## 原因三：GOLD-01 混合了不同失敗

| 題目 | 觀察到的 context | 判斷 |
|---|---|---|
| CP03、CP05、GR03 | 年份冒號清單，沒有 Markdown 表格 | 違反共同表格契約 |
| GR06、AR09 | 使用內部直線，但沒有 header delimiter row | 缺少表格必要結構；不能只補最外側直線就當合格 |
| RT07 | `項目 \| 113年`、`---\|---`、兩筆資料，沒有最外側直線 | parser 隱含限制；只補邊界直線後 parsed concept/year/value 完全吻合 evidence |
| RT04 | 同樣沒有邊界直線；列名「營業利益」而 fact 為「營業利益（損失）」 | 邊界解析與概念名稱等價性是兩個問題；不可把兩者合併自動通過 |

GFM 的表格規格允許省略最外側直線，仍需 header 與 delimiter row；本次只引用其表格語法判定，財務欄位檢查仍由本研究契約決定。[GFM §4.10 Tables](https://github.github.com/gfm/#tables-extension-)

`context_facts()` 目前跳過所有不以 `|` 開頭的行。對 RT07 而言，資料與結構已足夠，卻回報完全沒有表格。建議接受可選邊界直線，保留欄數、年份、有限數值與 exact selected rows 檢查。概念同義詞是否允許，是另一個待 rules review 決定的範圍；本次未改動。

## 原因四：TIME-02 與 TIME-01 是實際期間問題

- GR06、AR09、LG01、LG03、SF06、SF09、RT04：income-statement facts 的期間為全年，annotation 卻填 `period_type=duration, period_start=null`。共同 contract 明示 duration 為全年且日期完整；這 7 題不是把正確 instant 誤判成 duration。
- LG01：題目要求 113/114 年，即 2024/2025，選用 2023/2024 的收入。布林 True 剛好與 Gold Yes 同值，不代表 evidence 或年份正確。
- GR03：題目要求 2024/2025 的資產成長率，選用 2023/2024。公式形式正確，但輸入期間錯誤。

分類：**模型期間欄位或年度理解錯誤**。不能自動補 start date 或把 fiscal_year 視為僅供參考。YearValidator 在這些案例的失敗符合明示契約。

## 答案、型別與人工 labels

| 題目 | Generated answer | 實際 Python result | Gold answer | 關鍵差異 |
|---|---|---|---|---|
| GR06 | -2.63 | -2.69 | -2.69 | 生成答案與已寫程式不一致 |
| RT04 | 22.2 | 22.22 | 22.22 | 不是 22.20／22.2 的等價格式問題，而是數值不同 |
| GR03 | 2.0 | 1.97 | 1.54 | 答案不一致且 evidence 年度錯誤 |
| CP03 | 114年 | 執行失敗 | 2025 | 兩個 solution；unit=TWD_thousand 亦錯 |
| CP05 | 114年 | 114年 | 2025 | unit=TWD_thousand；contract 要求西元 scalar 與 year |
| LG03 | Yes | Yes | Yes | unit=TWD_thousand；typed answer check 因單位不同判錯 |

人工 labels 共 14 筆，Gemma 12 筆。Gemma 人工 false 欄位如下；未列者該題七項皆 true：

- CP03：logic_pass、python_reasoning_pass。
- CP05：logic_pass。
- LG01：time_pass、logic_pass、evidence_relevance_pass、golden_context_sufficiency_pass、python_reasoning_pass。
- GR03：time_pass、evidence_relevance_pass、golden_context_sufficiency_pass。

因此 Gemma 人工語意四項全部 true 為 8/12，但 semantic_parsing_accuracy 僅 2/12，差異來自 YearValidator 對完整期間的檢查。人工 true 不覆蓋 deterministic contract；本次未修改任何 label，也不重新替研究者判分。

## 為什麼格式問題修好仍不能推定 E2E 上升

E2E 使用六元件 AND。EvidenceValidator 同時檢查 context 與 Python grounding，且 evidence_accuracy、python_accuracy 都依賴它。因此一個 POT-01 會同時壓低 E 與 P。

11 題的 POT-01 與 CP03 的 POT-EXEC 是原始輸出中獨立存在的阻斷原因。**即使讓所有 UNIT-05 與 GOLD-01 通過，保留原 binding／執行要求時，原 12 題仍不會有 E2E 通過。**這是依必要條件作出的診斷推論，不是新增評分結果，亦不是放寬規則的實驗。

結論：應修正或明示格式契約，以避免把格式誤拒當成能力差；同時保留模型實際的 binding、日期、答案錯誤。不能為產生非零 E2E 而鬆綁這些要求。

## Qwen 對照與選模建議

Qwen 10/12 因 Tool call budget exceeded 沒有 annotation；剩下 SF06、SF09 也有 scalar/index 錯誤及 UNIT-05。SF06 fiscal_year=112 與西元 evidence 不符；SF09 把單位寫成額外單欄表格列。兩模型都受到格式問題影響，不能只替 Gemma 重評。

Gemma 相對 Qwen：schema 12/12 對 2/12、answer 6/12 對 2/12、execution 11/12 對 2/12、macro evidence F1 0.9167 對 0.1667、無輸出 0 對 10；平均題目耗時約 16.60 秒對 15.62 秒，但 Qwen 的數值包含大量提早失敗，不能單憑它認定 Qwen 完成有效標註較快。

**建議選 Gemma 作第一版 Generator／fresh-context Judge，且不做 tie-break；正式選擇仍由研究者決定並建立 selection record。**理由是交付完整標註、證據與執行穩定性明顯較好；不是因兩者 E2E=0 而宣稱平手，也不是宣稱 Gemma 已達正式實驗要求。此建議以 provisional Gold 與單次 Dev screening 為限。

## v1.1 修正與重評

研究者於 2026-09-16 明確確認「接受等價格式：修正解析器並對兩模型的原始輸出離線重評」。依此完成：

- UnitValidator／EvidenceValidator 的版本標記為 1.1，其餘 validator 維持 1.0。明確辨識「來源單位／單位／Source unit／Unit」標籤與新臺幣千元的台／臺、千／仟等價寫法；不做數量換算。
- 支援有效表格的可選最外側直線。新增支援的無左邊界 header 必須緊接欄數匹配的分隔列；保留舊 bordered-table 的既有契約。沒有擴張概念別名、修補資料列或改 Python bindings。
- CLI 新增 `evaluate-screening --revision <JSON>`。指定 revision 才可允許逐檔列出的評分程式差異；沒有 revision 仍須完全符合生成版本。
- Revision 需綁定 immutable manifest canonical hash、source／split hash、每個變動檔案的 before／after hash、原因與研究者授權。允許檔案限定評分與其 CLI 路徑，不能用此入口接受 prompt、rules、runner、模型設定或任意新模組漂移。
- 新 summary 與 `evaluation_provenance.json` 同時保存 revision、本次評分版本與原生成版本完整 hash。這是追溯記錄，不是身份認證或 cryptographic signature。

在專案根目錄執行的實際命令：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 evaluate-screening --experiment results/screening-001 --reviews results/screening-001/review-labels.jsonl --revision config/evaluation_revisions/screening-001-format-v1.1.json --output results/screening-001/evaluation-reviewed-v1.1
```

新舊結果比較：

| 指標 | Gemma 原版 | Gemma v1.1 | Qwen 原版 | Qwen v1.1 |
|---|---:|---:|---:|---:|
| E2E | 0/12 | 0/12 | 0/12 | 0/12 |
| Unit accuracy | 0/12 | 8/12 | 0/12 | 1/12 |
| Evidence accuracy | 0/12 | 0/12 | 0/12 | 0/12 |
| Python accuracy | 0/12 | 0/12 | 0/12 | 0/12 |
| Answer accuracy | 6/12 | 6/12 | 2/12 | 2/12 |
| Schema | 12/12 | 12/12 | 2/12 | 2/12 |
| Pending reviews | 0 | 0 | 0 | 0 |

Gemma 12 題 UNIT-05 全部消失，RT07 的 GOLD-01 消失；Qwen SF06 的 UNIT-05 消失。Gemma 的 POT-01 11 題、TIME-02 7 題、POT-02 3 題、TIME-01 2 題等保留。RT04 的 GOLD-01 從「沒有表格」變為列名與 fact 不完全相同；不替它自動套用概念同義詞。Qwen SF09 的單位嵌在不合欄寬的表格列中，仍保留失敗。

因此原先的必要條件推論已獲實際共同重評支持：格式誤拒修正後，剩餘真實 binding／期間／答案等錯誤仍令 E2E 為 0。

新產出 SHA256（原始檔案 bytes）：

| 檔案 | SHA256 |
|---|---|
| evaluation-reviewed-v1.1/summary.json | `b63e63798e5c34fcfa9c6a02cb8df3279774edccc3f18dd78c5df7942f532d4c` |
| evaluation-reviewed-v1.1/per_question.jsonl | `07dd9b70d06175e9b31e7de1b26bd9b97c32370f0884f1f0837548ef330c89da` |
| evaluation-reviewed-v1.1/evaluation_provenance.json | `43b0daf179b73510fc67a09b33cc18af4426fee7ad97d3b284d0de3b2ed20ffb` |

Results 與 artifacts/runtime 維持 `.gitignore` 排除，交接到另一台機器仍需另外移交。Revision JSON 與程式／測試／分析文件可納入 Git；不 force-add results。

## 下一步與待決策

1. 已完成格式政策確認、失敗測試、parser 修正及具版本紀錄的共同離線重評。保留舊結果並揭露新舊差異。
2. 已由研究者確認 Gemma、省略 tie-break，selection record 已建立；後續人工 review 見 [review_gate_v1.1.md](review_gate_v1.1.md)。
3. 完成 Gold、deterministic rules、Judge rubric review，再進 Dev A/B/C/D、tuning、Freeze、正式 Test。

本次範圍從診斷擴展到研究者明確核准的格式修正與共同重評。未自動修復原模型 annotation，未鬆綁數值／年份／binding，也未改變 A/B/C/D。正式模型選定與人工 review／freeze 不能由軟體測試代替。

## 驗證紀錄

- 原 24 題完整離線重現成功，逐題資料完全一致。
- 記憶體複本的單因素探針已定位 UNIT-05、POT-01、RT07 表格邊界問題；未用探針結果替代正式評分。
- 先加入回歸測試：原版 18 failed、9 passed，失敗涵蓋等價格式被拒與尚不存在的 revision 功能。實作後定向測試 50 passed；完整套件 **135 passed in 25.51s**。
- 未指定 revision 的實際 CLI 被拒絕，且沒有建立輸出目錄。指定精確 revision 後，兩模型 24 題重評成功。
- 交付前核對最初 95 個檔案：僅 3 個既有 source 檔與 1 個既有 test 檔為核准修改，其餘 91 個 hash 不變、無遺失；原 results、Gold、split、prompts、rules 及 derived 未變。新 revision、測試與新評分輸出另列，不覆寫舊產物。
- `git diff --check` 通過；新 results 與 runtime 重現資料持續被 `.gitignore` 排除。

依據：`prompts/contract.md`、`docs/experiment_protocol.md`、`docs/evaluation_rubric.md`、`config/rules.yaml`、`src/financial_annotation_harness/{validators,evaluation,screening_evaluation,python_executor,facts}.py` 及本報告列出的 immutable artifacts。
