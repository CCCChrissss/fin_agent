# 第一版實作交付紀錄

## 最新更新：縮減為兩個候選

依使用者確認，候選僅保留 qwen3.5:9b 與 gemma4:12b，移除 qwen3:14b 的設定與下載需求。初步 screening 改為12題 Development × 2模型 × B × 1 run＝24 question-runs；tie-break 仍追加12 × 2 × 2＝48 question-runs。正式模型未選定，A/B/C/D、Gold、Test 隔離與 retry 定義不變。

實際修改8個檔案：src/financial_annotation_harness/screening.py（候選數驗證）；config/screening.example.yaml（兩候選）；tests/test_screening.py、test_screening_evaluation.py、test_smoke.py（排程、評分、smoke 數量與拒絕第三候選）；docs/local_model_screening.md、README.md（目前操作規格）；本報告（交付紀錄）。沒有新增或刪除檔案。

驗證：screening、screening evaluation、smoke、既有 A/B/C/D runner 共18項相關測試通過；screen dry-run 回報 condition=B、partition=development、question_runs=24、no_API_called=true、winner=null。測試亦確認 tie-break 為48 runs。原始 Excel SHA256 保持9fea450f6937cc096f4f61dcf57be4901a139f9ba98588c3f2de2767aaa4a0ea。未執行模型下載、狀態查詢或真實推論。

與原計畫一致；另同步更新 README，避免首頁仍顯示三候選。下方三候選與36-run 數字屬當時的歷史驗證紀錄，不代表目前設定。

## 2026-09-15 Ollama-first 更新

本次依確認計畫新增 OllamaProvider、Development-only B screening、tie-break、離線模型比較、少量合成 smoke、Windows 環境快照與人工選模檢查。原始 Excel 及 experiment_protocol.md 未修改，A/B/C/D 定義未變。正式模型未選定，沒有執行正式 Test 或真實 screening。

新增核心檔案：`ollama_provider.py`、`screening.py`、`screening_evaluation.py`、`smoke.py`、`runtime_environment.py`，均位於 src/financial_annotation_harness。新增 `config/screening.example.yaml`、`docs/local_model_screening.md`，以及 tests/test_ollama_provider.py、test_screening.py、test_screening_evaluation.py、test_smoke.py、test_runtime_environment.py。

修改核心檔案：model_client.py（ModelProvider/factory）、config.py（Ollama 與模型身分）、runner.py（runtime/error/context trace）、cli.py（新命令）、governance.py（selection/runtime freeze）。既有 judge.py 與 trace.py 的 fresh context／journal 機制直接沿用，無須重寫；screening 評估另檔重用既有評分函数。

另修改 pyproject.toml／requirements.lock（httpx 明確相依，以既有 cache 離線編譯鎖定）、config/experiment.example.yaml（Ollama-first 但模型留空）、.env.example、.gitignore、README.md、implementation_design.md、reproducibility.md、evaluation_rubric.md 與本報告。新增 selection 與控制變因的 governance tests。沒有刪除檔案。

已執行驗證：108 項離線測試通過；25 個套件相依相容；screening dry-run=36，smoke dry-run=每候選2合成題+1Judge request；正式 Test dry-run 仍為576，允許的真實推論 calls=0。離線整合測試涵蓋匿名人工審查、Gold 評估、timeout 停止送新題、resume 不重抽、tie-break 控制、provider 工具轉換及同模型 Judge context 隔離。

一次 Ollama preflight 保存於 artifacts/runtime/ollama-preflight-20260915.json：版本0.33.3，指定三候選全部缺少。未啟動下載或監控。該次 WMI RAM 讀取未成功，後續改用 Windows GlobalMemoryStatusEx，單獨保存 artifacts/runtime/hardware-verified-20260915.json：RAM 33,454,280,704 bytes；RTX 5060 Ti，driver回報VRAM 16,311 MiB，driver 610.88。沒有為補 RAM 再查模型下載狀態。

與原計畫一致；尚未完成的是候選模型的真實 smoke，原因為三模型未安裝。沒有使用既有其他模型冒充候選驗證。模型下載完成後須由使用者通知，再做一次狀態確認、填妥版本/digest/量化/預算後進行少量 smoke。真實 smoke 不會自動接續36-run screening。詳細操作見 local_model_screening.md。

以下是本次更新前第一版的歷史交付紀錄，其中85項測試為當時結果。

日期：2026-09-15。工程範圍依確認的 Implementation Plan；研究定義仍以 experiment_protocol.md 為準。

## 完成範圍

已完成唯讀 Excel 稽核及衍生 SQLite、Financial Fact Search、共同 Annotation schema、A/B/C/D runner、八項 deterministic validators、獨立 Semantic Judge、最多兩次 feedback retry、Completion Gate、JSONL traces、Development/Test split、人工 freeze 檢查及離線 evaluation。

A 使用 baseline；B 增加 workflow guidance；C 在 B 上增加 deterministic validation 與 feedback retry；D 在 C 上增加 Semantic Judge 與 Completion Gate。A/B 不在線上驗證或修復。C/D 共用最多三次 attempt，Judge 不取得 Gold 或生成對話歷史。各組使用共同資料、工具、輸出契約與模型設定。

未加入 PDF OCR、向量資料庫、Raw PDF RAG、crawler、前端、附註 retrieval 或 multi-agent 平台。

## 新增檔案清單

| 路徑 | 用途 |
|---|---|
| pyproject.toml、requirements.lock | Python 3.12 套件定義與含 hash 的完整依賴鎖定 |
| src/financial_annotation_harness/__init__.py、__main__.py | 套件及 CLI 入口 |
| src/financial_annotation_harness/cli.py | 稽核、衍生資料、分割、freeze、run、demo、評估命令 |
| src/financial_annotation_harness/config.py | 嚴格設定與固定實驗條件 |
| src/financial_annotation_harness/schemas.py | Annotation、Search、Validator、Judge 結構契約 |
| src/financial_annotation_harness/io_utils.py | canonical JSON、hash、禁止覆寫的檔案輸出 |
| src/financial_annotation_harness/dataset.py | Excel 唯讀匯入、schema 稽核、分割、Gold Python 相容性檢查 |
| src/financial_annotation_harness/facts.py | SQLite 衍生事實庫及確定性搜尋 |
| src/financial_annotation_harness/python_executor.py | AST 限制、獨立子程序、逾時及資源限制 |
| src/financial_annotation_harness/validators.py | 八項驗證器、grounding、結果一致性與 failure codes |
| src/financial_annotation_harness/model_client.py | Scripted client 與明確啟用的 OpenAI adapter |
| src/financial_annotation_harness/judge.py | 獨立 Judge context 與 structured verdict |
| src/financial_annotation_harness/runner.py | 四組流程、重試及 Completion Gate |
| src/financial_annotation_harness/trace.py | 單一 writer、事件／attempt／final JSONL 與 hash 檢查 |
| src/financial_annotation_harness/governance.py | 人工 freeze、設定／原始碼／資料指紋與環境紀錄 |
| src/financial_annotation_harness/evaluation.py | Gold 離線評估、人工審查佇列、指標與 scope 獨立評估 |
| src/financial_annotation_harness/demo.py | 合成資料的完整離線示範 |
| prompts/contract.md、baseline.md、workflow.md、judge_rubric.md | 共用輸出契約及條件化提示 |
| config/rules.yaml、concept_aliases.yaml | 共用驗證規則與概念別名 |
| scripts/dev.ps1 | 專案自有 Windows 啟動及測試指令 |
| docs/implementation_design.md、evaluation_rubric.md、reproducibility.md、implementation_report.md | 設計、評分、操作與交付紀錄 |
| tests/conftest.py | 合成 fixtures、網路阻擋與專案內暫存目錄 |
| tests/test_dataset.py、test_facts.py、test_python_executor.py、test_validators.py | 資料、搜尋、受限執行器與驗證器測試 |
| tests/test_runner.py、test_judge.py、test_model_client.py | 組別差異、重試、Gate、Judge、mock SDK 測試 |
| tests/test_trace.py、test_evaluation.py、test_governance.py | Trace 完整性、評估指標、freeze 測試 |

修改：README.md（安裝與執行說明）、.env.example（模型與版本設定）、.gitignore（本機環境與產出排除）、config/experiment.example.yaml（嚴格設定範例）。沒有刪除檔案。

衍生產出：artifacts/derived/<Excel SHA256>/ 下的 SQLite、question inputs、metadata、Gold 副本與 manifests；artifacts/dataset_split.json；artifacts/runtime/ 下的驗證報告、合成示範與測試暫存。Gold 衍生副本只供離線評估，不送入模型。

## 實際驗證

- Windows / Python 3.12：85 項 pytest 通過；測試阻擋網路，未呼叫真實模型 API。
- uv pip check：25 個安裝套件相容。系統預設 uv cache 不可用，改用專案 artifacts/runtime/uv-cache 完成檢查，未改系統權限。
- 實際 workbook audit：7 sheets、60 questions、138 facts、60 Gold，errors 為空。
- 全部 60 段 Gold Python 實際執行成功，60 個結果符合 Gold Answer；報告為 artifacts/runtime/gold-python-compatibility.json。這只證明參考程式與執行器相容。
- 固定 split：每類 2 題 Development、8 題 Test，合計 12/48。
- 正式 Test dry-run：48 × 4 × 3 = 576 question-runs，允許真實 API calls 為 0。
- 合成示範 artifacts/runtime/synthetic-demo-final：12 question-runs 完成。A/B 保留錯誤，C/D 於第二次 attempt 修復；此結果不是模型成效證據。
- Excel SHA256 前後一致：9fea450f6937cc096f4f61dcf57be4901a139f9ba98588c3f2de2767aaa4a0ea。

## 與原計畫差異及限制

核心範圍與原計畫一致。為確保可稽核，額外明確化模型版本回傳檢查、固定規則檢查、離線 Gold Python 相容性命令，以及 opaque ID 排序的人工審查佇列。未更動研究條件或原始研究文件。

真實模型 adapter 僅經 mock 驗證，尚未驗證特定模型的實際 API 相容性或研究效果。尚未執行 Development／正式 Test，也未代替研究者完成 Gold 人工審核及 freeze。

中斷時採保守恢復：已完成紀錄可重建 final；請求送達狀態不明的題目封存 FAILED，不自動重抽。原始事件仍保留。這類失敗保留於分母，應另報基礎設施失敗數。

語意、context 充分性及 Python 推理是否正確需要獨立人工判定；在線 Judge PASS 不能直接作為 Gold 正確率。缺審查的相關指標顯示 null，不虛報為完成。

原始來源截圖及另立的 27 題 scope 題庫未提供；目前可追溯到 Excel，scope 只提供獨立評估入口，不能宣稱已完成該題庫實驗。

Python 執行器只支援受限財務運算子集，不是通用敵意程式 sandbox。macOS/Linux 提供入口與 POSIX 限制，但本次未在該平台執行測試。

## 研究者後續決定

確認 generator/judge 模型 snapshot 與預算；審查 Gold、規則和 rubric；使用 Development 調整後 freeze，再執行正式 Test 並完成獨立人工評分。原始 Excel 若需修訂，應由研究者建立新版本，不能由 importer 靜默修補。
