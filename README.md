# Financial Annotation Harness — TANET 2026

## 2026-09-28 專案封存與最新結果

本次 GitHub 上傳包含完整程式、設定、測試、唯讀 Gold Dataset、研究文件與去識別化實驗封存。下方 2026-09-16 執行更新及交接狀態為歷史紀錄，不代表目前仍在執行。

Protocol v1.1 的 60 題 × A/B/C/D × 1 次已完成，共 240 question-runs，pending review 為 0。最終 E2E：A 10/60（16.7%）、B 21/60（35.0%）、C 51/60（85.0%）、D 51/60（85.0%）。語意評分為 AI-assisted，Test 曾參與開發，結果屬固定版本回歸而非未接觸 holdout。

- [HTML 結果報告](reports/report.html)（下載後以瀏覽器開啟）
- [機器可讀結果](reports/analysis-summary.json)
- [研究設計與完整結果 Word](reports/財務問答標註實驗設計與完整實驗結果.docx)
- [封存內容、隱私處理與還原方式](research_archive/README.md)

首次執行歷史資料相關測試前，請先還原封存、建立 `artifacts/runtime`，並執行 `derive`。這些步驟不呼叫模型。原始 Gold 檔案保持位元組不變。

**2026-09-16 AI-assisted 執行更新：**研究者已授權 AI 代審並自主執行。Gold 的 60 題 Python/context 檢查與 AI 語意審查完成，非人工 review。Dev 144 題次已開始，背景流程會接續評分、凍結、Test 576 題次及結果彙整。最新階段為 `outputs/ai-assisted-study/status.json`；可直接開啟 `outputs/ai-assisted-study/experiment_results.html` 查看結果。使用 `config/experiment.ai-assisted.v1.json`，不再需要填寫人工工作簿才能推進；下文人工作業描述保留為原流程歷史。請勿重複啟動 runner。方法限制見 [AI review amendment](docs/ai_review_amendment.md)。

**最新交接狀態：**兩候選 screening 與14筆人工 review 已完成，pending_reviews=0；已正式選用 Gemma4 12B 作 Generator／fresh-context Judge，省略 tie-break；正式 Test 尚未開始。已完成 [E2E 根因分析與格式 parser v1.1 共同重評](docs/e2e_failure_analysis.md)：Gemma unit accuracy 提升至 8/12，E2E 仍為 0。Gold／rules／rubric 的人工審查已整合成 Excel，並提供自動完整性驗證與離線 Dev preflight；操作方式見 [人工審查 gate](docs/review_gate_v1.1.md)。

目前工程準備與驗證證據見 [Engineering Readiness v1.2](docs/engineering_readiness_v1.2.md)。除了人工審核與審核後才可解除的 live-call 保險外，Dev 前置工程已完成。

目前採 **Ollama-first / Windows**，已選定 **gemma4:12b**。已用 12 題 Development 的 Condition B 比較 qwen3.5:9b 與 gemma4:12b 兩個候選，共 24 question-runs；A/B/C/D 定義不變。完整命令與選模流程見 [Local Model Screening](docs/local_model_screening.md)。程式不下載模型、不監控下載，預設推論預算仍為 0。

第一版已提供唯讀 Excel 匯入、SQLite Fact Search、A/B/C/D runner、8 個 validators、獨立 Semantic Judge、Retry/Gate、JSONL traces 與離線 evaluation。預設不呼叫 API。

研究定義仍以 `docs/experiment_protocol.md` 為準。原始 Excel 不修改。完整設計與限制見 `docs/implementation_design.md`，評分規則見 `docs/evaluation_rubric.md`，重現與操作見 `docs/reproducibility.md`。

## Windows 快速開始

前置條件：Python **3.12**、`uv`；在本專案根目錄執行。建立環境與安裝會下載 Python 套件，但不呼叫模型 API。

```powershell
uv venv .venv --python 3.12
uv pip sync requirements.lock --python .venv/Scripts/python.exe --require-hashes
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 test -q
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 audit
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 derive
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 split
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 demo --output artifacts/runtime/my-demo
```

`test` 的成功判斷為全部測試通過。`audit` 應顯示 60 questions、138 facts、60 Gold、`errors: []`。`derive` 產生獨立衍生檔案並驗證來源 hash。`split` 固定每類 dev 2/test 8。`demo` 使用合成資料與 scripted client，驗證 A/B 保留錯誤、C/D 修復與評分，**不能作為模型研究結果**。重跑 demo 要使用新的 output 路徑。

命令若找不到 `.venv`，先完成環境安裝；若 source/schema/hash 檢查失敗，停止並檢查來源，不要刪除 Excel 或直接修改 Gold。

## macOS / Linux

同樣使用 Python 3.12、同一份 lock 與所有資料契約。在專案根目錄：

```bash
uv venv .venv --python 3.12
uv pip sync requirements.lock --python .venv/bin/python --require-hashes
export PYTHONPATH="$PWD/src"
.venv/bin/python -m pytest -q
.venv/bin/python -m financial_annotation_harness audit
.venv/bin/python -m financial_annotation_harness derive
.venv/bin/python -m financial_annotation_harness split
.venv/bin/python -m financial_annotation_harness demo --output artifacts/runtime/my-demo
```

平台測試狀態：本次實際驗證 Windows；macOS/Linux 入口與 POSIX 資源限制已提供，但尚未在該平台執行。

## 真實模型與正式測試

Screening 與人工選模已完成。目前設定在 `config/experiment.gemma4.v1.json`，selection record 在 `config/model_selection/gemma4-12b-v1.json`。先在 `financial_gold_review_v1.1.xlsx` 完成 `docs/review_gate_v1.1.md` 的人工審查並通過 `validate-review`／`dev-preflight`，再設定正式 max_live_calls；目前保留 0，不執行模型。OpenAI adapter 保留為可選用途，需另設 provider=openai、snapshot 與 OPENAI_API_KEY；不作為本次主要 runtime。CLI 不自動載入 `.env`。

只檢查執行規模、不呼叫 API：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 run --partition test --output results/main-study --dry-run
```

預期為 **576 question-runs**；這不是 API calls 數。Development 的完整四組三次 runs 為 144 question-runs。

實際執行、freeze 與 review 匯入命令見 `docs/reproducibility.md`。目前已有 live smoke、Development screening 與 reviewed evaluation；已完成 Gemma 選模，尚未完成 Gold review／freeze，詳見 `docs/CODEX_HANDOFF.md`。

---

以下保留 starter pack 的研究背景與檔案角色。

## Purpose

本資料夾提供 Codex 實作 TANET 2026 財務問答標註 Harness 實驗所需的最小研究規格與資料。

研究暫定題目：

**結合結構化簡明財報與 Harness Engineering 之可驗證財務問答標註框架**

## Included Files

```text
financial_annotation_harness_codex_pack/
├── data/
│   └── financial_qa_gold_dataset_v2.xlsx
├── docs/
│   ├── experiment_protocol.md
│   └── research_context.md
├── config/
│   └── experiment.example.yaml
├── .env.example
├── .gitignore
├── CODEX_START_PROMPT.md
└── README.md
```

## File Roles

### `data/financial_qa_gold_dataset_v2.xlsx`

研究 Gold Dataset 與 Financial Facts 的來源檔案。

**規則：視為 read-only，不得修改。**

需要 JSON / CSV / SQLite 時，請另外建立衍生資料。

### `docs/experiment_protocol.md`

正式的 Experiment Protocol v1.0，包含：

- A/B/C/D 四組實驗定義
- 控制變因
- Retry
- Validators
- Semantic Judge
- Completion Gate
- Metrics
- Failure Taxonomy
- Trace Schema
- Out-of-Scope Experiment

若工程實作與此文件衝突，請先指出衝突，不得自行修改研究設計。

### `docs/research_context.md`

研究背景、資料邊界與 Harness 設計原則。

### `config/experiment.example.yaml`

建議的實驗設定範例。實際值需在正式執行前由研究者確認。

### `.env.example`

API 與模型設定範例。

請自行複製為 `.env`，不要把真正 API Key 寫入 repository。

### `CODEX_START_PROMPT.md`

第一次交給 Codex 的建議 Prompt。

## Important Boundaries

第一版只需要：

- Structured Financial Fact Database
- Financial Fact Search Tool
- Annotation Runner
- A/B/C/D experiment conditions
- Deterministic Validators
- Semantic Judge
- Feedback Retry
- Completion Gate
- Trace Logging
- Evaluation Pipeline

第一版不要加入：

- PDF OCR
- Vector DB
- Raw PDF RAG
- XBRL crawler
- Web frontend
- 不必要的 Multi-Agent architecture

## Before Coding

Codex 必須先：

1. 檢查目前資料夾與 Dataset schema。
2. 說明對 A/B/C/D 的理解。
3. 提出 implementation plan。
4. 提出資料 schema 與 tool interface。
5. 列出預計建立／修改檔案。
6. 提出 testing strategy。
7. 等待人工確認後才開始實作。
