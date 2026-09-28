"""Mechanical offline scoring only; Gold never enters the pilot Generator/Judge."""
from pathlib import Path
import sys
import json
import argparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from financial_annotation_harness.io_utils import read_json, read_jsonl, file_hash, write_new_json
from financial_annotation_harness.config import load_rules
from financial_annotation_harness.evaluation import score_attempt
from financial_annotation_harness.facts import FactRepository


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prompt-version', choices=['1', '2'], default='1')
    args = parser.parse_args()
    folder = ROOT / 'outputs' / ('offline-repair-v1/dev-workflow-pilot' if args.prompt_version == '1' else 'dev-prompt-v2/workflow-pilot')
    if not (folder/'summary.json').exists():
        raise ValueError('Pilot not complete')
    derived = ROOT / 'artifacts/derived' / file_hash(ROOT/'data/financial_qa_gold_dataset_v2.xlsx')
    gold = {r['question_id']: r for r in read_jsonl(derived/'gold_annotations.jsonl')}
    inputs = {r['question_id']: r for r in read_jsonl(derived/'question_inputs.jsonl')}
    repo = FactRepository(derived/'financial_facts.sqlite')
    rows = []
    for p in sorted(folder.glob('run_01/[ABCD]/attempts.jsonl')):
        attempts = read_jsonl(p)
        for qid in read_json(folder/'manifest.json')['selected_ids']:
            r = [a for a in attempts if a['question_id']==qid][-1]
            q = inputs[r['public_question_id']]
            score = score_attempt(r, gold[qid], {'question_id': q['question_id'], 'question': q['zh']}, repo, load_rules(ROOT))
            rows.append({k: score[k] for k in ('condition','question_id','answer_accuracy','evidence_f1','python_execution_rate','python_answer_consistency','offline_failure_codes')})
    value = {'scope': 'Mechanical Dev pilot assessment; semantic correctness not independently adjudicated; not E2E accuracy', 'rows': rows}
    output = folder/'mechanical-assessment.json'
    if not output.exists():
        write_new_json(output, value)
    print(json.dumps(value))


if __name__ == '__main__':
    main()
