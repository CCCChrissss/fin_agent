補充核對方式：semantic_parse 是被審查的模型輸出，不是可信的題目規格。
semantic_parse_pass 的判斷必須對照原題與 time、concept、filter、logic 四個欄位；不能只看 evidence 或 answer 合理就略過欄位差異。

以下是虛構教學案例，與本次資料無關：
- 原題問「甲公司的營業利益」，annotation.filter 卻寫「乙公司」，即使 selected facts 屬於甲公司，semantic_parse_pass 仍為 false。錯誤是 annotation.semantic_parse.filter，failure_code=SEMANTIC_PARSE_ERROR。修正是把 filter 改回原題指定的公司，而不是更換正確的甲公司 facts。
- 原題問一年的金額，annotation.logic 卻寫計算年增率，即使 answer 恰好為正確金額，semantic_parse_pass 仍為 false；指出 semantic_parse.logic 的運算與原題不符。
- 原題與 annotation 的公司、期間、科目、運算皆一致，而且 Context 足以回答時，不要因為存在虛構教學案例而判 FAIL。

四個判斷欄位獨立負責各自項目。filter 不同只要破壞原題語意，就應記在 semantic_parse_pass；不要把正確的 selected fact 誤報為錯誤。
feedback 用一句話指出「原題要求、實際錯誤欄位、修正動作」，不要自行補造公司譯名。
維持原本四項 rubric、AND completion rule 與合法 failure codes，不增加新標準。
