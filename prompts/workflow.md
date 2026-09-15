按以下順序完成每次 annotation，包括修訂：
1. Semantic Decomposition：辨認 Time、Concept、Filter、Logic，將結果放入 semantic_parse。
2. Financial Concept Resolution：將原題概念對應至 Financial Facts 的列項，保留歸屬對象與報表期間。
3. Financial Fact Retrieval：透過工具取得所需 facts。
4. Evidence Selection：只保留完成題目全部推理必要的 operands/candidates。除 Single-Fact 外，不以直接等於答案的衍生列取代指定 operands。
5. Question Type：依最終主要邏輯選 Single-Fact、Comparison、Growth_Rate、Ratio、Logic 或 Arithmetic。
6. Golden Context：提供足以獨立重現指定推理的最小財務事實表。
7. Python Solution：區分 grounding、reasoning、formatting，將 evidence 綁定至語意變數。
8. Answer：提交依共同單位與格式規則表示的答案。
這些步驟的可觀察產物是結構化欄位與工具紀錄；不要求揭露隱藏推理。
