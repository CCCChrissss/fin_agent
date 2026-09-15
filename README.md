# Financial Annotation Harness — TANET 2026

目前採 **Ollama-first / Windows**，正式模型尚未選定。先用 12 題 Development 的 Condition B 篩選 qwen3.5:9b 與 gemma4:12b 兩個候選，共 24 question-runs；A/B/C/D 定義不變。完整命令與選模流程見 [Local Model Screening](docs/local_model_screening.md)。程式不下載模型、不監控下載，預設推論預算仍為 0。

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

先依 `docs/local_model_screening.md` 完成 preflight、smoke、screening 與人工選模。主實驗複製 `config/experiment.example.yaml` 為 `config/experiment.local.yaml`，填同一 Generator/Judge tag、digest、quantization、Ollama version 及 selection_record，再明確設定正的 max_live_calls。OpenAI adapter 保留為可選用途，需另設 provider=openai、snapshot 與 OPENAI_API_KEY；不作為本次主要 runtime。CLI 不自動載入 `.env`。

只檢查執行規模、不呼叫 API：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 run --partition test --output results/main-study --dry-run
```

預期為 **576 question-runs**；這不是 API calls 數。Development 的完整四組三次 runs 為 144 question-runs。

實際執行、freeze 與 review 匯入命令見 `docs/reproducibility.md`。本次實作沒有執行真實模型，也沒有代表研究者完成人工 Gold freeze。

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
