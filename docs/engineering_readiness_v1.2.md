# Engineering Readiness v1.2

日期：2026-09-16

本版本完成 Dev A/B/C/D 前可自動完成的工程準備，沒有執行正式 Test，也沒有修改原始 Gold Dataset。

## 已完成

- 建立 Excel 人工審核介面，整合 60 題 Gold、8 項 deterministic rules 與 6 項 Judge rubric。
- Gold Review 具有固定 ID／partition／record hash、下拉判定、備註、列狀態、篩選與凍結窗格。
- 新增 `validate-review`：檢查題目集合、hash、partition、四項判定、reviewer，以及拒絕項目的必要備註。
- 新增 `dev-preflight`：離線驗證 Gold 衍生資料、固定 split、A/B/C/D、3 runs、max retries=2、Gemma4 同模型 Generator/Judge 與 selection record。
- 具體化共同 contract：scalar/dictionary binding、duration/instant 日期、Markdown 等價格式、單位、Comparison/Logic answer 與 Python 結果一致性。
- 改善 validator feedback：TIME-02 回傳精確期間；POT-01 指出 scalar/index_key 修正；UNIT-02 指出必要答案單位；POT-02 同時記錄 annotation answer 與 Python result。
- 既有 runner 的 retry、completion gate、fresh-context Judge、no-Gold isolation、resume 與 fail-closed 測試持續保留。

## 自動驗證結果

- 空白交付工作簿：`validate-review` 正確回傳 `INCOMPLETE`，60 題全列為尚未審核。
- 暫存的全通過副本：`validate-review` 回傳 `COMPLETE`，`dev-preflight` 回傳 `READY`。
- 工作簿公式錯誤掃描：0 筆。
- 工作簿結構：60 題、Gold/Rules/Judge 三區皆有 data validation；Gold freeze pane 為 `E6`。
- 原始 Gold SHA256 維持 `9fea450f6937cc096f4f61dcf57be4901a139f9ba98588c3f2de2767aaa4a0ea`。

## 唯一待完成的人工作業

1. 在工作簿填 reviewer。
2. 完成 60 題四項 Gold 判定；不通過者填原因。
3. 完成 8 項 deterministic rules 判定；需調整者填原因。
4. 完成 6 項 Judge rubric 判定；需調整者填原因。

若任何項目選「不通過／需調整」，先依人工意見修改 Dev 可調整內容，再重新產生審核介面或保留同一 record hash 進行針對性複核。Test 題內容不得用於 prompt、rules 或 Judge tuning。

## 人工審核後

執行 `validate-review` 與 `dev-preflight`。兩者分別得到 `COMPLETE` 與 `READY` 後，才移除 `max_live_calls=0` 的執行保險、執行 12 題 Dev A/B/C/D。Dev tuning 結束後再 freeze v1.0；正式 Test 仍維持最後才執行。

