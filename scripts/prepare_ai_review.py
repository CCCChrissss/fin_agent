"""Record Codex's explicit semantic review with independent mechanical checks.

This script records the review in the conversation; it is not a semantic judge.
It never writes the source workbook or supplies Gold to the online runner.
"""
from pathlib import Path
from collections import Counter
from decimal import Decimal
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from financial_annotation_harness.dataset import inspect_dataset
from financial_annotation_harness.human_review import build_review_payload
from financial_annotation_harness.io_utils import read_json, timestamp, write_new_json, digest
from financial_annotation_harness.validators import context_facts

# Individually reviewed in Codex; not model predictions or synthetic labels.
NOTES = {
    "AR01": "2025流動與非流動資產相加，保留兩個操作數。",
    "AR02": "2024流動與非流動負債相加。",
    "AR03": "2023稅前淨利減所得稅，不能以本期淨利列取代操作數。",
    "AR04": "2025營收減營業成本。",
    "AR05": "2023至2025三年營收平均，分母3。",
    "AR06": "依題意加總三年已揭露EPS；不是合併期間重新估算EPS。",
    "AR07": "2025資產減負債；結果雖等於權益仍須兩個操作數。",
    "AR08": "2024母公司權益加資產負債表非控制權益。",
    "AR09": "2025本期淨利加負數其他綜合損益。",
    "AR10": "2023營業利益減2025，方向符合高多少。",
    "CP01": "三年營收最大值在2025。", "CP02": "三年營業利益最小值在2025。",
    "CP03": "三年年末資產最大值在2025。", "CP04": "三年年末負債最小值在2024。",
    "CP05": "三年年末權益最大值在2025。", "CP06": "三年年末流動資產最小值在2024。",
    "CP07": "三年營業費用最大值在2025。", "CP08": "其他綜合損益含負數，最大值在2024。",
    "CP09": "淨利歸屬非控制權益非資產負債表NCI；最低為2025負值。",
    "CP10": "母公司業主權益而非權益總計，最大值在2025。",
    "GR01": "營收2024對2023，以2023為分母。", "GR02": "營收2025對2024，以2024為分母。",
    "GR03": "年末資產2025對2024成長率。", "GR04": "年末負債2024對2023負成長。",
    "GR05": "營業利益2025對2024負成長。", "GR06": "毛利2024對2023負成長。",
    "GR07": "營業費用2025對2024成長。", "GR08": "權益2024對2023成長。",
    "GR09": "本期淨利2025對2024负成長。", "GR10": "EPS2025對2024，以3.8為分母。",
    "LG01": "2025營收大於2024，Yes。", "LG02": "2024年末資產大於2023，Yes。",
    "LG03": "三年淨利每相鄰年度皆嚴格下降。", "LG04": "2025其他綜合損益小於零；僅需單一fact與零常數。",
    "LG05": "2025負債低於權益。", "LG06": "三年流動資產/資產皆低於40%，any=False。",
    "LG07": "營業費用三年相鄰比較均增加。",
    "LG08": "依Gold定義，期間內兩個相鄰年變化：營收增加且營業利益下降；不包含2022至2023變化。題目每年措辭有此解讀限制。",
    "LG09": "先以各年毛利除營收，再逐年比較毛利率。", "LG10": "2025資產等於負債加權益，三個fact。",
    "RT01": "2025流動資產/資產。", "RT02": "2025流動負債/負債。", "RT03": "2025毛利/營收。",
    "RT04": "2024營業利益/營收。", "RT05": "2023本期淨利/營收。", "RT06": "2025負債/資產。",
    "RT07": "2024權益/資產。", "RT08": "2025營業費用/營收。", "RT09": "2023所得稅/稅前淨利。",
    "RT10": "2025資產負債表非控制權益/權益；非當期損益NCI。",
    "SF01": "2025年度營收直接取值。", "SF02": "2024年末資產直接取值。",
    "SF03": "2023本期淨利非母公司歸屬淨利。", "SF04": "2025年末流動負債。",
    "SF05": "2024年末權益總計。", "SF06": "2023年度營業利益。",
    "SF07": "2025基本EPS，來源元非仟元。", "SF08": "2024綜合損益歸屬母公司，非淨利歸屬母公司。",
    "SF09": "2025其他綜合損益淨額為負。", "SF10": "2023年末資產負債表非控制權益。",
}

def main():
    payload = build_review_payload(ROOT)
    original = inspect_dataset(ROOT / "data/financial_qa_gold_dataset_v2.xlsx")
    facts = {f["Fact_ID"]: f for f in original["facts"]}
    execution = read_json(ROOT / "artifacts/runtime/ai-review-gold-python-20260916.json")
    executed = {r["question_id"]: r for r in execution["results"]}
    assert set(NOTES) == {r["question_id"] for r in payload["rows"]}
    assert execution["source_sha256"] == payload["source_sha256"]
    rows = []
    for row in payload["rows"]:
        selected = [facts[f.strip()] for f in row["source_fact_ids"].split(";")]
        expected = Counter((f["Concept_ZH"], f["Fiscal_Year"], Decimal(str(f["Value"]))) for f in selected)
        actual = Counter(context_facts(row["golden_context"]))
        qid = row["question_id"]
        mechanical = expected == actual and executed[qid]["execution_pass"] and executed[qid]["answer_match"]
        rows.append({"question_id": qid, "partition": row["partition"], "gold_record_hash": row["gold_record_hash"],
                     "review_kind": "ai_assisted", "reviewer": "Codex AI (current conversation)",
                     "semantic_review_pass": True, "context_matches_source": expected == actual,
                     "python_execution_and_answer_pass": bool(mechanical), "rationale": NOTES[qid]})
    report = {"review_kind": "ai_assisted", "reviewer": "Codex AI (current conversation)",
        "human_review_completed": False, "status": "COMPLETE" if all(r["python_execution_and_answer_pass"] for r in rows) else "NEEDS_CHANGES",
        "source_sha256": payload["source_sha256"], "question_count": len(rows), "reviewed_question_count": len(rows),
        "rules_reviewed": True, "judge_rubric_reviewed": True, "reviewed_at": timestamp(),
        "authorization": "Researcher requested AI judgment and autonomous experiment execution in this conversation.",
        "rule_review_notes": "Existing strict contracts retained across A/B/C/D; no Test-based tuning. Heuristic question-type validators can have false negatives and will be reported.",
        "judge_review_notes": "Confirmed four semantic criteria only, fresh two-message context, no Gold/history, malformed verdict fail-closed. Workbook wording about formulas is broader than the actual online rubric; code/rubric controls.",
        "limitations": ["No independent human semantic review", "No external statement-to-workbook verification", "LG08 interpreted as adjacent changes within 2023-2025", "AI reviewer also developed harness; not blinded"],
        "rows": rows}
    write_new_json(ROOT / "artifacts/runtime/ai-gold-review-20260916.json", report)
    settings = read_json(ROOT / "config/experiment.gemma4.v1.json")
    settings.update(max_live_calls=20000, review_mode="ai_assisted", review_record="artifacts/runtime/ai-gold-review-20260916.json")
    write_new_json(ROOT / "config/experiment.ai-assisted.v1.json", settings)
    print(json.dumps({"status": report["status"], "reviewed": len(rows), "report_hash": digest(report)}))

if __name__ == "__main__":
    main()
