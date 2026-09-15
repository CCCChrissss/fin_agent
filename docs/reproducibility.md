# Reproducibility and operation

**最新主要路徑：Ollama / Windows。**先閱讀 [Local Model Screening](local_model_screening.md)，完成同一模型 Generator/Judge 的人工選擇。下方「真實 Development」的 OpenAI 設定保留為可選 adapter 說明，不是本次正式研究預設。原有 freeze、evaluate 命令仍適用，但 Ollama 另檢查 selection 與 runtime/hardware 身分。

所有 Windows 命令在專案根目錄執行。使用 Python 3.12、uv、requirements.lock (含 hashes)。不需啟動服務或資料庫 daemon。

## 開發與離線驗證

```powershell
uv venv .venv --python 3.12
uv pip sync requirements.lock --python .venv/Scripts/python.exe --require-hashes
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 test -q
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 audit
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 derive
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 split
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 verify-gold-python --output artifacts/runtime/gold-python-check-new.json
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 demo --output artifacts/runtime/demo-new
```

測試預設阻擋 socket.connect；mock provider 完整檢查 request 參數但不發網路。每次 pytest 使用專案 artifacts/runtime 下全新 UUID 暫存路徑，不修改系統 Temp ACL、不刪除既有使用者目錄。scripts/dev.ps1 只在程序期間設定 PYTHONPATH，不修改永久 ExecutionPolicy。

derive 重跑只驗證原有輸出，不能靜默覆寫已變更資料。split 演算法是 canonical JSON [seed, question_type, original_id] 的 SHA256 排序，每類前2 dev、後8 test，固定 seed=20260915；對輸入 row order 不敏感。實際清單在 artifacts/dataset_split.json，可審閱但不應手動重抽挑題。

## 真實 Development

1. 複製 config/experiment.example.yaml 為 config/experiment.local.yaml。
2. 設定 provider=openai，generator_model/judge_model 與實際回傳的 generator_version/judge_version。模型名稱與參數不由程式猜測。
3. 明確設 max_live_calls 預算；先使用 --dry-run 檢查規模。API call budget 是 generator+judge 的總和，不是 question 數。
4. 在 shell 設 OPENAI_API_KEY。不要寫入 YAML、trace 或版本控制。CLI 不自動載入 .env。
5. 以下 **--live 會產生真實 API 成本**；本次實作未執行這些命令。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 run --config config/experiment.local.yaml --partition development --output results/development-001 --dry-run
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 run --config config/experiment.local.yaml --partition development --output results/development-001 --live
```

完整 Development 是12題×4組×3次=144 question-runs。錯誤 response 不會被 SDK 自動 retry。API 版本回傳與指定 snapshot 不一致直接失敗。僅 Development 可用來修改 prompt/rubric/rules；修改後產生新的 study/output。

設定優先序：嚴格 YAML → 明確非空環境變數 override → 保存 resolved settings。OPENAI_MODEL、OPENAI_MODEL_VERSION、OPENAI_JUDGE_MODEL、OPENAI_JUDGE_MODEL_VERSION、GENERATOR_TEMPERATURE、JUDGE_TEMPERATURE、MAX_TOKENS 可覆寫；MAX_RETRIES 若設為非2拒絕。其他未知 YAML keys 拒絕，不會忽略。

## 人工 freeze 與正式 Test

先人工審查 Gold 語意/evidence/公式、評估 rubric 與所有共同規則。此 attestation 是研究者的決策，不是讓程式自動批准。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 freeze --config config/experiment.local.yaml --reviewer ResearcherName --attestation gold-and-rules-reviewed
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 run --config config/experiment.local.yaml --partition test --output results/main-001 --live
```

48×4×3=576 question-runs。freeze 保存 source、split、schema、resolved config、code、prompts、rules、lock 等 hash；任何變更阻止正式 run。不要編輯 freeze JSON 繞過檢查。若需改研究設計，保留舊 study 並建立明確新版本／regression study。

## Evaluation 與 review

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 evaluate --experiment results/main-001 --output results/main-001/evaluation-initial
```

讀取 evaluation-initial/review_queue.jsonl，另存人工填寫的 labels 檔，保留 ID/hash，填全部七項 boolean 與 reviewer，再執行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 evaluate --experiment results/main-001 --reviews results/main-001/review-labels.jsonl --output results/main-001/evaluation-reviewed
```

只有這一步才可得到已審定語意與最終 E2E；如果有已知錯誤元件，未審題亦可先確定 E2E=0。每次 evaluation 使用新輸出目錄、不覆寫報告。缺失/重複 runs、錯誤 trace hash、未知 review IDs、artifact mismatch 會停止評估。

## 恢復與限制

`run ... --resume --live` 只能使用完全相同 controls/data/code。已完成題目跳過、已完成稿但缺 final 的情況重建 final；delivery 不明的中斷題目封存 FAILED，不重新抽樣。總 API call budget 在 resume 時根據 request events 累計。殘留 writer lock 先確認 PID 不再執行，再由操作者移開；禁止同時兩個 writer。

JSONL 所有 raw responses 可包含題目和生成內容，分享前應檢視。沒有隱藏 chain-of-thought 請求，不將 API key 記入 manifest。SDK 錯誤不直接抄錄可能包含憑證的 response body。

本次 Windows 實際驗證；macOS/Linux 啟動命令見 README。Job Object/AST/subprocess 不是通用 hostile-code 安全保證，支援範圍外程式應失敗而非降級執行。
