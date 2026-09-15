# Experiment Protocol v1.0

## 1. 研究目的

本研究探討：在相同大型語言模型、相同結構化簡明財報資料庫、相同財務問答測試集與相同輸出格式下，逐步加入不同程度的 Harness 元件，是否能提升財務 QA 標註的正確性、可驗證性與錯誤修復能力。

本研究主要自變數為 **Harness Level**。其餘條件原則上固定。

### Research Questions

- **RQ1**：將人工標註流程結構化為 Guided Workflow，是否優於無引導的 LLM Baseline？
- **RQ2**：加入 Deterministic Validator 與 Feedback Loop，是否能降低可由程式判斷的錯誤？
- **RQ3**：在 Deterministic Harness 之上加入 Semantic Judge，是否能進一步降低 Concept、Evidence 等語意錯誤？
- **RQ4（次要）**：Full Harness 是否能辨識簡明財報資料不足的 Out-of-Scope 問題，降低 unsupported answer / hallucination？

---

## 2. 研究資料

### 2.1 Gold Dataset

資料檔：

`data/financial_qa_gold_dataset_v2.xlsx`

此檔視為 **read-only source data**。任何程式實作若需要 JSON、CSV、SQLite 或其他衍生格式，必須建立新檔案，不得覆寫或修改原始 Gold Dataset。

目前資料集包含 60 題平衡財務 QA 題目：

- Single-Fact：10 題
- Comparison：10 題
- Growth_Rate：10 題
- Ratio：10 題
- Logic：10 題
- Arithmetic：10 題

Gold record 主要包含：

- Question
- Time
- Concept
- Filter
- Logic
- Question Type
- Required Financial Facts
- Golden Context
- Python Solution
- Gold Answer
- Unit

資料庫範圍只涵蓋簡明財報，不納入財報附註、地區別收入、退休金、金融工具、公司特有揭露等資訊。

### 2.2 Gold Freeze

正式測試前需完成一次人工語意審查。完成後將 Gold Dataset 與 Test Set 凍結。

正式 Test 開始後，不可因 Test 題目錯誤而修改：

- Gold Answer
- Gold Evidence
- Harness Rule
- Judge Rubric
- Prompt

若後續根據 Test failure 改善 Harness，需視為額外 Regression Study，不可回填主實驗結果。

---

## 3. Dataset Split

採用 stratified split。

每種 Question Type 10 題：

- Development：2 題
- Test：8 題

總計：

- Development Set：12 題
- Test Set：48 題

Development Set 可用於：

- Prompt 設計
- Workflow 設計
- Validator 開發
- Semantic Judge Rubric 調整
- Retry Feedback 設計

Test Set 在正式實驗前必須 freeze。

Split 必須可重現，建議將最終 split 以獨立檔案保存，例如：

`artifacts/dataset_split.json`

---

## 4. 共同控制條件

A、B、C、D 四組必須保持下列條件一致：

- Generator Model
- Model Version
- Financial Database
- Financial Fact Search Tool
- 48 Test Questions
- Temperature
- Max Tokens
- Output Schema
- Unit Rules
- Gold Dataset

唯一主要差異為 Harness Level。

模型與參數不得 hard-code，需由 config / environment 設定。

---

## 5. Financial Fact Search Tool

四組實驗應使用相同的 Financial Fact Search Tool。

概念介面示例：

```text
search_financial_facts(
    query,
    years=None,
    statement_type=None,
    top_k=None
)
```

建議回傳結構：

```json
{
  "success": true,
  "query": "operating revenue",
  "candidates": [
    {
      "fact_id": "...",
      "concept": "營業收入",
      "year": 114,
      "value": 237553199,
      "unit": "TWD_thousand",
      "statement": "income_statement"
    }
  ],
  "missing_information": [],
  "retry_suggestion": null,
  "recommended_next_action": "select_evidence"
}
```

Tool 本身應為 deterministic data access，不應自行回答問題。

---

## 6. Experimental Conditions

### 6.1 A — Unguided LLM Baseline

目的：建立模型在無流程控制與外部驗證下的基準能力。

提供：

- Question
- Output Schema
- Financial Fact Search Tool

不提供：

- 強制 Workflow
- Validator
- Judge
- Feedback
- Retry

流程：

```text
Question
→ LLM + Financial Fact Tool
→ Final Annotation
```

模型第一次提交完整 Final Annotation 即結束。

---

### 6.2 B — Structured Workflow

目的：驗證人工標註 Workflow 作為 Guide 是否能提高第一次完成品質。

流程固定為：

```text
Question
→ Semantic Decomposition
  - Time
  - Concept
  - Filter
  - Logic
→ Financial Concept Resolution
→ Financial Fact Retrieval
→ Evidence Selection
→ Question Type
→ Golden Context
→ Python Solution
→ Answer
```

B 組不包含外部 Validator，不因外部 Validation 進行 Retry。

若模型自行產生錯誤 Evidence、Python、Unit 或 Answer，仍直接作為最終輸出。

---

### 6.3 C — Deterministic Harness

目的：驗證 Computational Sensors + Structured Feedback 的效果。

C = B + Deterministic Validators + Retry。

流程：

```text
Structured Workflow
→ Draft Annotation
→ Deterministic Validation
  ├─ PASS → Final Annotation
  └─ FAIL → Structured Feedback → Retry → Validation
```

#### 必要 Validators

1. `SchemaValidator`
   - Required fields 是否完整
   - 型別是否合法

2. `FactExistenceValidator`
   - referenced fact_id 是否存在於 Financial Facts

3. `YearValidator`
   - 年份是否存在且符合題目時間需求

4. `UnitValidator`
   - 財報原始單位與輸出單位轉換是否合理

5. `EvidenceValidator`
   - Required Facts 是否都出現在 Golden Context
   - 不允許使用不存在的 fact/value

6. `PythonSyntaxValidator`
   - Python 是否可安全執行

7. `PythonResultValidator`
   - Python Result 是否與 Final Answer 一致

8. `QuestionTypeValidator`
   - Question Type 與主要 Formula / Operator 是否相符

#### Retry

- Initial Attempt：1 次
- Maximum Retry：2 次
- Max Attempts：3 次

失敗 Feedback 必須指出：

- failure_code
- failed rule
- observed value
- expected constraint
- recommended correction

C 組 **不得使用 Semantic Judge**。

---

### 6.4 D — Full Harness

目的：驗證在 deterministic validation 之上加入 inferential semantic validation 的額外效益。

D = C + Semantic Judge + Completion Gate。

流程：

```text
Structured Workflow
→ Draft Annotation
→ Deterministic Validation
→ Semantic Judge
  ├─ PASS → Completion Gate → ACCEPTED
  └─ FAIL → Semantic Feedback → Retry
```

#### Semantic Judge 僅檢查需要語意理解的項目

1. Semantic Decomposition
   - Time / Concept / Filter / Logic 是否符合原問題

2. Concept Mapping / Resolution
   - selected financial concept 是否真正回答題目

3. Evidence Relevance
   - selected facts 是否與題目語意相關

4. Golden Context Sufficiency
   - Golden Context 是否足以獨立完成指定推理

不得把以下 deterministic 問題重新交給 Judge：

- Python 是否可執行
- Python Result == Answer
- Fact ID 是否存在
- Year 是否存在
- Schema 是否完整

#### Judge Context

Semantic Judge 應使用 fresh / independent context。

Judge 不讀取 Generator 的隱藏推理歷史，只讀取：

- Original Question
- Generated Structured Artifact
- Candidate / selected Financial Facts
- Judge Rubric

Judge output 建議 schema：

```json
{
  "semantic_parse_pass": true,
  "concept_pass": true,
  "evidence_pass": false,
  "golden_context_pass": true,
  "overall_pass": false,
  "failure_code": "WRONG_EVIDENCE",
  "feedback": "The selected evidence does not support the requested concept."
}
```

Judge Temperature 建議設為 0。

#### Completion Gate

只有以下全部通過才能 `ACCEPTED`：

```text
Required Schema PASS
AND Fact Validation PASS
AND Year PASS
AND Unit PASS
AND Python Execution PASS
AND Python Result PASS
AND Semantic Judge PASS
```

若達到 Max Attempts 仍無法通過：

`final_status = FAILED`

---

## 7. Output Artifact Schema

四組最終均應輸出相同的 annotation schema，至少包含：

```json
{
  "question_id": "...",
  "semantic_parse": {
    "time": [],
    "concept": [],
    "filter": [],
    "logic": ""
  },
  "question_type": "",
  "retrieved_fact_ids": [],
  "golden_context": "",
  "python_solution": "",
  "answer": null,
  "unit": ""
}
```

A/B/C/D 不得使用不同 final schema。

---

## 8. Primary Metric

### End-to-End Annotation Accuracy

單題需同時滿足：

```text
Semantic Parse 正確
AND Question Type 正確
AND Evidence 正確
AND Python 正確
AND Answer 正確
AND Unit 正確
```

才計為 E2E = 1。

公式：

```text
E2E Accuracy = 完全正確的標註筆數 / 總題數
```

---

## 9. Secondary Metrics

需計算：

- Semantic Parsing Accuracy
- Question Type Accuracy
- Evidence Precision
- Evidence Recall
- Evidence F1
- Answer Accuracy
- Python Execution Rate
- Python-Answer Consistency
- Unit Accuracy
- First-pass Accuracy
- Final Accuracy
- Recovery Rate

### Recovery Rate

```text
Recovery Rate
= 第一次錯誤但最後修正成功的題數
  / 第一次錯誤的題數
```

---

## 10. Failure Taxonomy

每次 validation / judge failure 應記錄固定 Failure Code：

```text
SCHEMA_ERROR
SEMANTIC_PARSE_ERROR
CONCEPT_ERROR
EVIDENCE_ERROR
YEAR_ERROR
UNIT_ERROR
QUESTION_TYPE_ERROR
FORMULA_ERROR
PYTHON_EXECUTION_ERROR
PYTHON_ANSWER_MISMATCH
UNSUPPORTED_ANSWER
OTHER
```

Failure code 需可用於後續 A/B/C/D failure analysis。

---

## 11. Repeated Runs

正式主實驗：

```text
48 Test Questions
× 4 Conditions
× 3 Runs
= 576 question-runs
```

需保存每次獨立 run 的結果，不可只保存平均值。

若 API / provider 支援 seed，應固定並記錄。

每次 run 至少記錄：

- model
- model_version
- temperature
- prompt_version
- timestamp
- run_index

結果報告至少提供 Mean 與 Standard Deviation；若時間允許，補 95% Confidence Interval。

---

## 12. Statistical Comparison

主要 pairwise comparison：

- A vs B
- B vs C
- C vs D

同一批題目屬 paired observations，可考慮使用 McNemar's Test 比較二元正誤結果。

若進行多組 pairwise testing，建議使用 Holm correction。

統計方法屬建議項目，不應阻塞第一版 runner 實作。

---

## 13. Experiment 2 — Out-of-Scope Detection

次要實驗使用簡明財報無法支持的問題。

只比較：

- A — Unguided Baseline
- D — Full Harness

正確行為示例：

```json
{
  "status": "OUT_OF_SCOPE",
  "missing_information": [
    "customer-level accounts receivable"
  ]
}
```

不得在缺乏 Evidence 的情況下硬回答。

主要指標：

- Scope Detection Accuracy
- Precision
- Recall
- F1
- Unsupported Answer Rate

若使用 27 題：

```text
27 Questions × 2 Conditions × 3 Runs = 162 runs
```

此實驗不得與主實驗 E2E Accuracy 混算。

---

## 14. Trace Logging

不得只保存 Final Answer。

每個 attempt 至少保存：

```json
{
  "run_id": "...",
  "question_id": "...",
  "condition": "C",
  "run_index": 1,
  "attempt": 2,
  "model": "...",
  "model_version": "...",
  "prompt_version": "...",
  "semantic_parse": {},
  "tool_calls": [],
  "retrieved_fact_ids": [],
  "golden_context": "...",
  "python_solution": "...",
  "python_result": null,
  "final_answer": null,
  "unit": "",
  "validator_results": {},
  "judge_result": null,
  "failure_codes": [],
  "final_status": "ACCEPTED",
  "input_tokens": null,
  "output_tokens": null,
  "latency_ms": null,
  "timestamp": "..."
}
```

Trace 應使用 external state（JSONL / SQLite / Parquet 皆可），不可僅依靠 LLM context。

---

## 15. Research Boundary

第一版明確不做：

- PDF OCR
- PDF layout parsing
- Vector Database
- RAG over raw PDF
- XBRL crawler
- Web frontend
- 完整財報附註 retrieval
- 不必要的 Multi-Agent orchestration

第一版需要完成：

- Structured Financial Fact Database
- Financial Fact Search Tool
- Annotation Runner
- A/B/C/D Experiment Conditions
- Deterministic Validators
- Semantic Judge
- Feedback Retry
- Completion Gate
- Trace Logger
- Evaluation Pipeline

