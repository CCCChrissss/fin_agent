# Offline evaluation rubric v1

評估在生成產物封存後進行，四組共同使用同一 evaluator，沒有回饋至模型。online Judge PASS/Gate ACCEPTED 都不是 Gold 正確性的標籤。

## 主實驗

逐題 E2E = semantic parse AND question type AND evidence AND Python correctness AND answer AND unit。

- Semantic Parse：人工分別評 Time/Concept/Filter/Logic，另要求 deterministic 年度一致。接受語意等價表達，不要求逐字等於 Gold。
- Question Type：與 Gold 相同。
- Evidence：選用 ID 集合等於 Gold、fact/value/context/grounding 一致，且人工確認 relevance 與 context sufficiency。數值相等不代表概念等價。
- Python correctness：受限執行成功、result 等於 Gold、result 等於 generated answer、grounding/主要運算 checks 通過，且人工確認指定推理正確。不能只以「程式與自己答案一致」判對，也不要求程式字串等同 Gold。
- Answer：typed scalar，依單位與格式對照 Gold。數字嚴格相等，沒有隱藏 tolerance；前置共同輸出 contract 要求 percentages round(...,2)。3.80 與 3.8 相同；0.02 與 2 不同。明確民國年轉為西元；Yes/No、是/否、boolean 可正規化，不能把 bool 當 monetary 1/0。
- Unit：正規化後等同 Gold，且線上單位規則檢查通過。

FAILED 仍在固定分母。若有末稿，評其六元件；沒有有效 artifact 則判 0。Gate 誤拒的正確末稿可能 E2E=1，接受率另報，不添加第七個成功條件。基礎設施失敗不從分母移除，需在 failure analysis 揭露。主要正式 Test 分母每組每 run 為 48，不只計 ACCEPTED。

## 語意審查

evaluate 產生 review_queue.jsonl，含 opaque review_id、artifact_hash、原題、生成 artifact、Gold 語意/context/Python 與空白評分欄。沒有 condition、run_index 或 online Judge 結果，避免直接提示組別。

審查者只編輯另外的 review labels 檔，填 reviewer，以及 time_pass、concept_pass、filter_pass、logic_pass、evidence_relevance_pass、golden_context_sufficiency_pass、python_reasoning_pass 七個 boolean。保留 review_id/artifact_hash。評分欄位全填後再匯入；錯誤 ID、hash、重複/未知 review、缺少 boolean 都會被拒绝。review_queue 中保留生成 question_id 作資料一致性，不含 Gold 題型前綴。

建議第二位審查者獨立抽查，分歧在 freeze 的 rubric 下 adjudicate，不修改原始 Gold。軟體無法證明填寫者確為人工，此為研究治理責任。合成 demo 以明確標示的 fixture oracle 評分，不得移植為主實驗 labels。

未審但有有效 artifact 時，相關語意分數為 null；若某個已知必要元件已錯，E2E 可確定為 0。存在未定案 E2E 的 group 不報最終平均數，保留 pending count，不以 null=0 或忽略 pending 樣本美化結果。

## 指標

Evidence P=|P∩G|/|P|、R=|P∩G|/|G|、F1=2PR/(P+R)。P 是最終選用 ID 集合，不是所有 search candidates；重複不加分。主資料 Gold evidence 非空，空預測 P/R/F1=0。保存逐題與 macro/micro。非法 ID 留在 P，計為 FP。

Python execution rate 與 Python-answer consistency 以全部題數為分母；執行失敗不算一致。First-pass/Final Accuracy 各用第一稿/terminal 稿 E2E。Recovery = first=0 且 final=1 / first=0；分母 0 為 null，不是 0。A/B first=final，若有錯題 recovery=0。

每 run 保留結果，3 runs 算 Mean 與 sample SD (ddof=1)，不只保存平均值。另保存題型分組與 online/offline failure counts。McNemar/Holm/CI 不在第一版強制範圍；不能把同一題三次重複視為獨立題目樣本。

## Out-of-Scope 評估入口

evaluate-scope 單獨接收 JSONL：question_id、gold_out_of_scope:boolean、status:OUT_OF_SCOPE|ANSWERED|FAILED、answer。請每個 condition/run 分別提供一個檔案。以 Out-of-Scope 為 positive，報 scope accuracy/P/R/F1、unsupported answer rate；failed 不能算正確偵測。只有 positive 題目時明示無法衡量 in-scope false positives。此入口不能與主實驗 E2E 混算；OOS 題庫與生成流程仍待研究者提供及核准。
# Local screening 補充

Screening 使用同一 Gold/E2E 人工審查規則，新增 JSON parse、schema、retrieval、Python execution、latency 與 runtime failure 指標；定義及分母見 local_model_screening.md。它不與主實驗 A/B/C/D 成績混算，不用在線 Judge PASS 取代人工正確性，不自動選定模型。
