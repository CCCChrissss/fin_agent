# AI review amendment — 2026-09-16

研究者於本次對話明確授權 Codex 代為審查及執行實驗，以加速研討會投稿。本修訂只變更審查來源，不變更 A/B/C/D、固定 Generator/Judge、12/48 split、3 runs、maximum retries=2 或評分分母。

Gold 的內部一致性由程式核對；語意由 Codex AI 審查，不宣稱為人工審查或外部財報原件查證。原始 Excel 不修改。Test Gold 的閱讀僅用於審查，禁止用於改 prompt、rules、retrieval 或 Judge。未提供原始財報影像，無法證明 workbook 與公開財報一致。

Dev 與 Test 的離線語意評分若使用 AI，必須保存每一 artifact 的 review_id、artifact_hash、reviewer、review_kind、判定與理由。不得把 D 組線上 Judge verdict 當作離線正確答案。評分報告標記 AI-adjudicated；不得宣稱獨立人工驗證。程式可驗證的 Answer Accuracy、Evidence set P/R/F1、Python execution/consistency 與 AI-adjudicated E2E 分別呈現。

正式 Test 之前凍結 source、split、prompts、rules、程式、模型參數、runtime 及本修訂。使用獨立的 ai-reviewed-gold-and-rules attestation，不得冒用原 human attestation。保留原人工審核工作簿為未完成。

方法限制：同一 Codex 協助工程及 AI review，並非盲化的獨立人類評審；AI 可能有關聯錯誤。AI-assisted result 應如實標示為探索性證據，不保證正向結果或投稿接受。
