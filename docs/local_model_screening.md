# Local Model Screening 決策與操作

本文件是使用者核准的研究環境補充決策。`experiment_protocol.md` 的 A/B/C/D、Gold、Retry 與正式 Test 定義維持原樣。正式環境為本地 Windows；本次不擴充 macOS/Linux 相容性。

## 研究次序與邊界

Ollama preflight → 少量真實 smoke → 12 Dev × 2 models × B × 1 run → 人工比較／必要時 tie-break → 選定 Generator/Judge → Gold、rules、rubric review → 12 Dev 的 A/B/C/D → 調整 Harness → Freeze v1.0 → 48 Test × 4 × 3 → 獨立 evaluation。

候選僅存在 config：qwen3.5:9b、gemma4:12b。沒有正式預設 winner。主實驗的 Generator 與 Judge 必須是相同 tag/digest/quantization；Judge 使用獨立 request/context，不取得 Generator history、thinking、Gold 或執行驗證標籤。

Screening 固定使用現有 Development split，拒絕改為 Test、C/D、額外 retry 或並行執行。首次非工具回應直接保存，沒有 schema 自動修補或 provider 強制 JSON grammar。B 線上不跑 validators/Judge，離線 evaluator 才取得 Gold。

## 安裝與一次檢查

以下在專案根目錄、已建立 Python 3.12 `.venv` 的 PowerShell 執行。Ollama 是外部 runtime，程式不代為安裝或啟動服務。

```powershell
uv pip sync requirements.lock --python .venv/Scripts/python.exe --require-hashes --cache-dir artifacts/runtime/uv-cache
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 test -q
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 ollama-preflight --output artifacts/runtime/ollama-preflight-new.json
```

preflight 只各讀一次 runtime version、model inventory，保存 Windows／GPU／VRAM／RAM／driver。`ram_bytes` 為 bytes，`vram_mib` 為驅動回報 MiB；不把顯示卡行銷容量當作實測值。讀不到則明列 unknown，不虛構。它不下載、推論或監控。

缺模型時由使用者執行所需命令：

```powershell
ollama pull qwen3.5:9b
ollama pull gemma4:12b
```

下載完成後再通知協作者。不要建立 polling loop、重複 list/ps/pull status、讀取 terminal 等待百分比，或為下載建立長時間背景監控。程式中沒有 pull 實作。

## 建立 screening 設定

複製 `config/screening.example.yaml` 為 `config/screening.local.yaml`；從 preflight 填入 `settings.model.expected_ollama_version`、每個候選的 `digest`、`quantization`。將 `settings.max_live_calls` 設為明確正整數。這是整場 warm-up + Generator/Judge 的推論 request 上限，不是題數；24 題可能含多次 tool interaction。

共同初始值：num_ctx=8192、max_tokens→Ollama num_predict=4096、temperature=0、seed=20260915、connect timeout=5s、request timeout=300s、question deadline=900s。兩候選共用設定；每個候選 `think` 明確控制 thinking。無支援的可選設定以 null 表示不送出，並在 config 記錄理由，不以錯誤後自動降級的方式修改。

`top_p`、`top_k`、`repeat_penalty` 可明確設定；null 表示使用模型／runtime 預設，不代表已知數值。manifest 保存模型原始 parameters/template、runtime version、request parameters。無法從 API 確認的服務啟動參數應由研究者另外保存；不能宣稱所有有效預設都已量測。

`structured_output_mode` 固定 prompt_only。更改為強制 JSON schema 應另立研究設定，不能為某個候選偷偷增加限制。所有核心模型名稱均由 config 決定。

Screening 設定不讀取 OpenAI 環境變數；主實驗 Ollama 設定也忽略 OPENAI_MODEL 等名稱覆寫，避免沿用舊雲端設定。CLI 不自動載入 `.env`。

## Smoke：少量真實推論

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 smoke --config config/screening.local.yaml --output results/smoke-001 --dry-run
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 smoke --config config/screening.local.yaml --output results/smoke-001 --live
```

每候選兩個相同合成案例：單事實、跨年成長率；另做一次 fresh-context Judge request。成功條件為原生 request 正常、工具執行且有候選、annotation 可 parse／符合 schema、Python 可執行、Judge verdict 可 parse，並能保存模型參數及延遲。

Python 診斷在 B 輸出後執行，不送回模型。如果成長率 annotation 不合法，Judge 接線測試使用明確標記 `used_fixture=true` 的合成 artifact；這不能算模型成功完成整條流程。Judge PASS 也不等於人工 Gold 正確。

Smoke 不自動啟動 screening，不可作為模型排名依據。timeout、HTTP error、malformed response 與工具格式錯誤主要由 mock tests 驗證，避免真實重複失敗成本。

## 初步 screening 與 tie-break

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 screen --config config/screening.local.yaml --output results/screening-001 --dry-run
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 screen --config config/screening.local.yaml --output results/screening-001 --live
```

dry-run 應為 24 question-runs、不呼叫 API。初始每模型 run 1、每次 12 題。固定題目排序，模型依 config 順序逐個執行，單一 writer。每模型一個固定 warm-up request，不列入成績，單獨 trace；模型完成後一次 unload，避免下一模型與前模型同時常駐。

Tie-break 另存 `config/screening-tiebreak.local.yaml`：保留原設定，只將 stage 改 tie_break、保留兩候選、run_indices=[2,3]，填 parent_experiment 與 tie_break_reason。它補 48 question-runs，不能覆寫 run 1。比較資料、prompt/code、共同設定及候選 profile，任一不一致則拒絕合併為同一次 screening。

建議判斷接近的標準為前兩名 E2E 差距不超過一题或品質／速度取捨不明，但程式不自動觸發 tie-break 或選 winner。12 題的一題差距約 8.33 個百分點，單次估計不能當成穩健顯著差異。

## 評分與選模

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 evaluate-screening --experiment results/screening-001 --output results/screening-001/evaluation-initial
# 將 review_queue 另存為填妥全部七項 boolean、reviewer 的 labels 檔
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 evaluate-screening --experiment results/screening-001 --reviews results/screening-001/review-labels.jsonl --output results/screening-001/evaluation-reviewed
# 有 tie-break 時一次載入兩個來源，labels 必須對應這兩批 artifacts
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 evaluate-screening --experiment results/screening-001 results/screening-tiebreak-001 --output results/screening-combined-evaluation
```

產出 per_question.jsonl、per_run.jsonl、model_comparison.csv、summary.json、匿名 review_queue.jsonl、selection_template.json。沒有人工語意判定時，E2E 保留 null/pending；已知確定錯誤可為 0。所有失敗留在分母，缺整題紀錄則報 incomplete，不排除後算高分。

指標包括 E2E、schema、JSON parse、Evidence macro/micro P/R/F1、Python execution、Answer、retrieval、latency、timeout、推論失敗、無輸出及無法 parse 次數。JSON 合法但 schema 錯誤另計。Python execution 衡量受限 executor 是否可執行，即使其他 schema 欄位失敗亦可單獨量測；E2E 規則不因此放寬。

Financial Fact Retrieval Success 定義為至少一次合法工具查詢，且累積工具 candidates 包含全部 Gold required fact IDs。另報 candidate recall、非空搜尋比例、合法 tool call 成功率；不把有任意搜尋結果誤當取得正確證據。

Mean latency 為每題第一個 request 到終止狀態的 wall time，包含工具；另外報正常提交輸出的均值及全體中位數。Timeout 保留實際耗時；request 原始 durations_ns、load_duration 與 token counts 保存在 trace，不能把 nanoseconds 當 milliseconds。單次 screening 不虛構 SD；有多次 runs 才提供 E2E sample SD。

人工填寫 selection_template：status=SELECTED、reviewer、reason、candidate_id、tag、digest、quantization、Ollama version、evaluation_summary_path（專案相對路徑）。保留 evaluation_summary_hash。程式驗證審查已完成、模型 profile 與評估來源相符。以 annotation 品質、schema、evidence、Python、速度綜合選擇，不自動建立加權排名。

主實驗 config 指向 `selection_record`，並將 Generator/Judge tag 與 digest 設成同一模型。之後才使用既有 Development A/B/C/D 及 freeze 命令。Freeze 保存 selection hash、runtime 模型 metadata、硬體與既有 source/split/code/rules/prompts hashes；正式 Test 啟動必須相符。

## 恢復與失敗處理

輸出不覆寫，resume 需相同設定、資料、程式及環境。完成題目不重新抽樣；送達不明的題目封存 FAILED。Screening 遇 timeout/connection/budget failure 停止繼續送新題，保留 journal；操作者確認本機無殘留推論後，才明確使用 --resume。沒有重試 HTTP，也不自動等待 server 恢復。

max_wall_seconds 為單次 screening 啟動的排程時間上限，於題目邊界檢查；正在執行的一題另受 question timeout 約束，因此可超出排程上限至多一題時間。重啟需明確 --resume，總 request budget 由既有事件累計。中斷 warm-up 不自動補抽，需另建有說明的研究輸出。

`.local.yaml` 不納入共用 code hash，因為 resolved settings 已各自保存／hash；加入 tie-break 操作設定不應被當作變更原始碼。原始碼、共同範例、prompts/rules 變更仍會使比較失效。舊研究輸出不要用修改後程式強行重評，應保留對應原始碼版本。

## 依據

- Ollama native chat：https://docs.ollama.com/api/chat
- Tool message contract：https://docs.ollama.com/capabilities/tool-calling
- Structured output 與 thinking：https://docs.ollama.com/capabilities/structured-outputs 、https://docs.ollama.com/capabilities/thinking
- 模型 digest 與 quantization：https://docs.ollama.com/api/tags

本次修改未對兩個候選做真實推論，因此實際模型能力與參數相容性仍待 smoke 驗證。
