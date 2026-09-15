# Codex Initial Prompt

請先不要修改或建立任何程式碼。

這是一個 TANET 2026 研究實驗專案，研究主題暫定為：

「結合結構化簡明財報與 Harness Engineering 之可驗證財務問答標註框架」

請先完整閱讀：

- `data/financial_qa_gold_dataset_v2.xlsx`
- `docs/experiment_protocol.md`
- `docs/research_context.md`
- `README.md`

其中 Excel 為本研究目前的 Gold Dataset，請視為 **read-only**，不得修改原始資料。如果實作需要 JSON、CSV、SQLite 或其他格式，請建立衍生資料。

本研究核心不是建立完整財報 RAG 或 Multi-Agent 平台，而是建立一套 **可重現、可追蹤、可驗證的 Financial Annotation Experiment Harness**。

第一版只需要支援：

- Structured Financial Fact Database
- Financial Fact Search Tool
- Annotation Runner
- A/B/C/D Experiment Conditions
- Deterministic Validators
- Semantic Judge
- Feedback Retry
- Completion Gate
- Trace Logging
- Evaluation Pipeline

不要加入：

- PDF OCR
- Vector Database
- Raw PDF RAG
- XBRL crawler
- Web frontend
- 財報附註 Retrieval
- 不必要的 Multi-Agent architecture

研究實驗的 A/B/C/D、控制變因、最大 Retry、Metrics、Failure Code 與 Trace 要求，均以 `docs/experiment_protocol.md` 為準，不得因工程方便自行改變實驗變因。

## 在開始實作前，請先完成以下分析

1. 分析 Excel Dataset 的實際 workbook / sheet / column schema，並指出任何與研究規格不一致或可能影響實作的地方。
2. 說明你對 A/B/C/D 四組實驗的理解，以及各組唯一增加的 Harness 元件。
3. 提出建議專案架構，優先小型、可維護、可重現，不要過度設計。
4. 提出衍生 Financial Fact Database schema，並說明如何確保原始 Excel read-only。
5. 提出 Financial Fact Search Tool interface 與 Tool Result schema。
6. 提出 Annotation Output schema。
7. 提出每個 Deterministic Validator 的 interface、責任與 failure code。
8. 提出 Semantic Judge interface、rubric input 與 structured output schema。
9. 提出 Retry / Completion Gate state machine。
10. 提出 Trace schema 與檔案儲存方式。
11. 提出 Evaluation pipeline，包括 E2E Accuracy、Evidence Precision/Recall/F1、Answer Accuracy、Python consistency、First-pass / Final Accuracy、Recovery Rate。
12. 提出 Development/Test stratified split 的可重現方式。
13. 列出預計新增、修改或刪除的檔案與用途。
14. 說明測試策略，包括 unit test、integration test、fixture 與如何避免呼叫真實 API 造成不必要成本。
15. 指出你目前認為研究規格中仍存在的歧義、風險或需要人工決定的地方。

請先只回覆 Implementation Plan，不要開始建立或修改程式碼。等我確認後再實作。
