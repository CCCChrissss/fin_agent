# Implementation design v1

Ollama-first 補充：核心以 ModelProvider 抽象、OllamaProvider 原生 /api/chat、OpenAI adapter 與 scripted tests 組成。獨立 screening 排程只重用 B，不放寬主實驗四組三次約束；詳見 local_model_screening.md。正式 Generator/Judge 同模型獨立 context。

此文件記錄使用者核准 Implementation Plan 後採用的工程解讀，沒有改寫 experiment_protocol.md。

## 架構與資料邊界

單一 Python package + CLI。沒有 Web UI、OCR、向量 DB、raw PDF RAG、XBRL crawler 或 Multi-Agent framework。

`dataset.py` 唯讀 Excel、驗證資料及衍生 artifacts；`facts.py` 只讀 facts SQLite；`runner.py` 處理條件、tools、attempt、feedback；`validators.py` 不讀 Gold；`judge.py` 建立獨立 context；`evaluation.py` 才能讀 Gold。`schemas.py` 是四組共用契約。

SQLite 只允許 financial_facts 與 dataset_sources 兩張表。原始 Question_ID 只存在 metadata/trace；Generator 的 QuestionInput 只含中性 question_id、原題與語言。原始 ID 前綴不可用來提示題型。衍生 Gold 不進入 provider messages。

Excel hash：`9fea450f6937cc096f4f61dcf57be4901a139f9ba98588c3f2de2767aaa4a0ea`。匯入不使用 save/export，不把空值當 0。GOLD-02 雖在 Excel Table 外，仍從 sheet 讀入。`source_manifest.json` 保存所有衍生檔案 hash；建立到一半失敗的目錄會被判為不完整，不會覆寫。

## 已採用的契約解讀

- A=共同 contract+baseline；B=A+workflow guide；C=B+8 validators+最多兩次 retry；D=C+semantic judge+completion gate。
- B/C/D 的 workflow 是同一順序的 prompt guide 與工具迴圈；不額外以多次固定 LLM calls 強制每個階段。可觀察欄位與 tool calls 會被保存，不宣稱能觀測模型隱藏思考顺序。
- C/D 共用最多 3 attempts。單一 attempt 可進行多次 tool interaction，受共同上限限制。
- A/B 首次非工具回應立即提交，malformed JSON 也原樣保存；沒有自動 JSON 修复、validators、judge 或 retry。
- Required Facts 在线上代表明確時間限制、模型宣告的 evidence 與程式 operands 的一致性，不使用 Gold evidence 修正模型。語意選錯由 D/離線人工審查處理，C 不假裝有語意 oracle。
- D Gate 要求同一稿全部 8 validators PASS，且四個 Judge criteria 全部 PASS。SKIPPED/ERROR 不能當 PASS。
- terminal status：A/B `SUBMITTED`；C `VALIDATED`；D `ACCEPTED`；耗盡 attempts/基礎設施錯誤為 `FAILED`。
- 固定 failure codes 以 protocol §10 為準；Judge 範例的 WRONG_EVIDENCE 正規化為 EVIDENCE_ERROR。
- selected_evidence 是四組共同增加的結構化 grounding，不由 Runner 自動填補。
- retrieved_fact_ids 定義為最終選用 IDs；所有搜尋 candidates 在 tool trace。Ratio 的前兩項 selected evidence 為分子、分母，這只檢查宣告順序與程式一致，不宣稱已判斷題目語意方向。
- 共同答案契約：金額保持來源單位，v1 不接受隱含的仟元/元 rescaling；Growth/Ratio 為百分點、Python round(...,2)，Comparison 為西元年，Logic 為 Yes/No。UnitValidator 對不支援的換算報錯，不默默自動換算。
- Golden Context 為簡單 Markdown table，數字可含千分位、年份可民國/西元；fact/value/年度必須和 selected evidence 相符，並標示來源單位。
- 語意解析使用 typed time records；同年混合 instant/duration 不在目前單一報表題目契約範圍。若未來擴展跨表混合期間，需要新 schema/version。

## Python execution

獨立 CPython worker，支援目前資料所需的數字、dict、comprehension 與基本运算。執行前 AST allowlist、禁止 imports/private names/dynamic calls/recursion/loops/任意 attributes；worker 不接收 DB、Gold、API client 或 key。暫存 CWD、isolated interpreter、timeout 與記憶體上限。

Windows 使用 Job Object process memory limit；POSIX 使用 resource limits。無法設定限制時 fail closed。這是受限財務程式 executor，不是提供給任意攻擊者的通用多租戶 sandbox。

EvidenceValidator 對照實際 locals、Context 表格、程式回傳依賴；不能只列出 evidence 卻 return 硬編答案。這仍不是通用程式等價證明：dict 中每個 key 的實際動態使用、複雜算式的數學等價、額外 prose 的語意與 Golden Context 最小必要性由獨立 review 判斷。QuestionTypeValidator 只做可判定的主要語法/公式一致性，不把中間除法一律分類成 Ratio。

## Trace、錯誤與恢復

每次 model request/response、tool result、draft 都先寫入 events.jsonl，attempts/finals 另寫。fsync、record hash、單 writer lock、防止重複 finals。記錄 raw content、schema 錯誤、完整 validator feedback、Judge raw response/usage、執行結果、tokens、latency、版本、seed。

`transport_retries=0`，SDK 也關閉隱藏 retry。API/Judge 格式錯誤記 OTHER + infrastructure_error，不當作語意失敗反覆抽樣。已完成 resume 不再呼叫模型；未完成且 delivery 不明的題目保守封存 FAILED，不重新送出。已存 terminal attempt 但未存 final 時重建 final 引用。若程序異常留下 .writer.lock，操作者須確認 PID 已終止，再移開該鎖檔；程式不自動清除活躍鎖。

執行環境、source/split/config/schema/code/prompts/rules/dependencies hashes 在 manifest/freeze 中保存。provider response 的 model 名稱必須與指定 version 相符，否則視為 drift 報錯。指定 seed 僅在設定 supports_seed=true 時傳送，run seed 為 base_seed + run_index - 1，同一 run 四組一致。

## 第一版範圍與待人工事項

已實作主實驗 runner 與独立 scope metric 入口。27 題 OOS 題庫未提供，拒答生成 schema 與樣本組成也尚未 freeze；因此不提供冒稱完成的 Experiment 2 生成結果。不能把主實驗 failed answer 當成 OOS 偵測結果。

正式 live 測試仍需人工確認模型版本與參數支援、Gold 語意/evidence/公式、人工 evaluation rubric、呼叫預算及 final freeze。開發不能以 Test feedback 修改主實驗；改版應另開 regression study。

模型 adapter 依官方 Chat Completions 的工具呼叫 request/result 流程實作，未使用 provider-side schema auto-repair：
- https://developers.openai.com/api/docs/guides/function-calling
- https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create

實際鎖定的 SDK 與所有 transitive dependencies 見 requirements.lock。
