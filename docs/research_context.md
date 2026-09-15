# Research Context

## 1. 專案名稱

Financial Annotation Harness for Verifiable Financial QA Annotation

暫定中文研究題目：

**結合結構化簡明財報與 Harness Engineering 之可驗證財務問答標註框架**

暫定英文題目：

**A Verifiable Financial QA Annotation Framework Using Structured Financial Statements and Harness Engineering**

---

## 2. 研究背景

本研究源自財務問答資料標註工作。財務 QA 的建立不只是產生答案，而是需要依序完成：

1. 理解財務問題
2. 辨認 Time / Concept / Filter / Logic
3. 找到對應財務資料
4. 建立 Evidence / Golden Context
5. 判斷 Question Type
6. 建立可重現的 Python Solution
7. 計算 Answer
8. 驗證年度、單位、證據與答案一致性

大型語言模型具備語意理解與生成能力，但單次生成仍可能產生：

- Concept 誤判
- Evidence 選錯
- 年份錯誤
- Unit 錯誤
- 計算公式錯誤
- Python 與 Answer 不一致
- Golden Context 不足
- unsupported answer / hallucination

本研究因此不是追求 Perfect Prompt，而是將人工標註流程轉成 **Guide + Sensor + Feedback Loop + Completion Gate** 的 Financial Annotation Harness。

---

## 3. 核心研究原則

### Capability ≠ Harness

Capability 解決「模型能不能做」。

Harness 解決：

- 做得對不對
- 做完了沒有
- 做錯了如何修正
- 如何避免錯誤直接進入最終結果

### Guides

在模型行動之前或執行過程中提供結構與限制，提高第一次做對的機率。

本研究主要 Guides：

- Semantic Decomposition
- Question Type 規則
- Evidence Rule
- Golden Context Rule
- Python Solution Rule
- Unit Rule
- Structured Workflow

### Sensors

執行後驗證結果。

分為：

#### Computational Sensors

可由程式客觀判定：

- Schema
- Fact existence
- Year
- Unit
- Python execution
- Python result
- Answer consistency
- Evidence completeness

#### Inferential Sensors

需要語意理解：

- Semantic Decomposition correctness
- Concept Mapping / Resolution
- Evidence Relevance
- Golden Context Sufficiency

**原則：能用 deterministic rule 判斷，就不要優先使用 LLM Judge。**

---

## 4. Data Scope

目前實驗只使用聯電的結構化簡明財報資料。

主要範圍：

- 簡明資產負債表
- 簡明綜合損益表

不使用：

- 財報附註
- PDF OCR / Layout Parsing
- XBRL retrieval
- 技術平台別、地區別、客戶別等公司特有細項
- 退休金、衍生工具等附註細節

這是刻意的 controlled environment，目的是把研究焦點放在 Annotation Workflow 與 Harness Reliability，而不是 PDF parsing 或 Retrieval noise。

---

## 5. Question Types

資料集使用六種題型：

1. **Single-Fact**
   - 直接取得單一財務事實

2. **Comparison**
   - 最大、最小、跨年度比較、排序

3. **Growth_Rate**
   - 跨期間成長率或變動百分比

4. **Ratio**
   - 分子 / 分母之比例

5. **Logic**
   - 條件判斷、正負、是否大於或小於某條件

6. **Arithmetic**
   - 一般加減乘除、平均、百分比等數值運算

目前 Gold Dataset 為六類各 10 題，共 60 題。

---

## 6. Core Annotation Fields

系統最終輸出至少應涵蓋：

- Time
- Concept
- Filter
- Logic
- Question Type
- Retrieved Financial Fact IDs
- Golden Context
- Python Solution
- Python Result
- Answer
- Unit

研究評估的核心不是模型是否輸出漂亮解釋，而是上述 structured artifacts 是否正確、可追溯、可重現。

---

## 7. Golden Context 原則

Golden Context 應只包含完成題目所需的最小必要 Evidence。

除 Single-Fact 外，若財報存在一個直接等於最終答案的衍生列項，但題目原本要求透過 operands 推理得到答案，Golden Context 原則上不直接提供該衍生列項，以避免答案洩漏。

例：若題目要求「流動資產 + 非流動資產」，Golden Context 應提供兩個 operands，而不直接放入「資產總計」。

---

## 8. Python Solution 原則

Python Solution 需：

- 使用 semantic variable names
- 避免 magic numbers
- 明確區分 Grounding / Reasoning / Formatting
- 可實際執行
- 執行結果需與 Answer 一致

LLM 不應被視為數值運算的唯一執行者；數學結果應由可重現的程式運算驗證。

---

## 9. Experiment Core

研究主實驗為四組逐層增加 Harness 元件的 Ablation Study：

- A — Unguided LLM Baseline
- B — Structured Workflow
- C — Deterministic Harness
- D — Full Harness

詳細規則請參考：

`docs/experiment_protocol.md`

---

## 10. 不應自行擴張的方向

第一版實驗不應因工程便利或模型能力而自行加入：

- Vector DB
- Raw PDF RAG
- OCR
- XBRL crawler
- Web UI
- Multi-Agent platform
- 財報附註搜尋

若未來要加入上述能力，應視為新的研究變因或 Future Work，而不是目前主實驗的一部分。

---

## 11. 研究目標輸出

本研究最終希望回答：

1. Guided Workflow 是否改善財務 QA annotation？
2. Deterministic validation 能消除哪些 mechanical / numerical errors？
3. Semantic Judge 是否能補足 deterministic rules 無法處理的 semantic failures？
4. Feedback Loop 是否能有效修復第一輪錯誤？
5. Full Harness 是否能降低沒有 Evidence 時的 unsupported answer？

