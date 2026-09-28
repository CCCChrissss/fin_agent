"""Eight question-runs: bounded Dev engineering probe, not a new formal experiment."""
import json
import argparse
from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from financial_annotation_harness.cli import load_prompts
from financial_annotation_harness.config import load_settings, load_rules
from financial_annotation_harness.dataset import verify_derived
from financial_annotation_harness.facts import FactRepository
from financial_annotation_harness.governance import project_hashes
from financial_annotation_harness.io_utils import read_json, read_jsonl, write_new_json, digest, file_hash
from financial_annotation_harness.ollama_provider import OllamaProvider
from financial_annotation_harness.runner import AnnotationRunner
from financial_annotation_harness.schemas import QuestionInput
from financial_annotation_harness.trace import TraceStore

WORKFLOW_REMINDER = '''執行要求：這是實際資料查詢，不是示範或填寫範本。
完成語意分解與概念解析後，立即使用 search_financial_facts 取得資料；尚未取得資料時下一個動作應為工具呼叫。
query 只填財務科目，年份放 years。收到工具結果後，才繼續 evidence、題型、Context、Python、Answer。
逐字沿用工具回傳的 fact_id 與來源數值，不使用 fact_1、示意值或記憶中的數字。
Context 按共同 contract 橫向排版：第一欄必須為「項目」，後續欄名為年份，每一資料列包含科目及各年份值，並有 delimiter row。
最後提交完整 annotation JSON。這些步驟不提供外部驗證或額外重試。'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prompt-version', choices=['1', '2'], default='1')
    args = parser.parse_args()
    folder = ROOT / 'outputs' / ('offline-repair-v1/dev-workflow-pilot' if args.prompt_version == '1' else 'dev-prompt-v2/workflow-pilot')
    original = read_json(ROOT / 'results/dev-ai-assisted-001/manifest.json')
    if original['project_hashes'] != project_hashes(ROOT):
        raise ValueError('Frozen code changed')
    split = read_json(ROOT / 'artifacts/dataset_split.json')
    ids = [sorted(split['groups'][kind]['development'])[0] for kind in ('Arithmetic', 'Single-Fact')]
    settings = load_settings(ROOT / 'config/experiment.ai-assisted.v1.json')
    prompts = load_prompts(ROOT)
    if args.prompt_version == '2':
        from dev_prompt_candidates import generator_prompts
        prompts = generator_prompts(prompts)
    else:
        prompts['workflow'] += '\n' + WORKFLOW_REMINDER
    manifest = {'kind': 'Dev engineering probe; no inferential claims', 'selected_ids': ids,
                'selection': 'Lexically first Development ID in Arithmetic and Single-Fact',
                'conditions': list('ABCD'), 'run_index': 1, 'question_runs': 8,
                'prompts': prompts, 'prompt_hash': digest(prompts), 'settings': settings.model_dump(),
                'original_manifest_hash': digest(original), 'script_hash': file_hash(Path(__file__)),
                'judge': 'Original frozen rubric; candidate rubric not promoted',
                'core_hashes': project_hashes(ROOT)}
    folder.mkdir(parents=True, exist_ok=True)
    mp = folder / 'manifest.json'
    if mp.exists():
        if read_json(mp) != manifest:
            raise ValueError('Pilot drift')
    else:
        write_new_json(mp, manifest)
    source = ROOT / 'data/financial_qa_gold_dataset_v2.xlsx'
    derived = ROOT / 'artifacts/derived' / file_hash(source)
    verify_derived(source, derived)
    inputs = {q['question_id']: q for q in read_jsonl(derived / 'question_inputs.jsonl')}
    aliases = {q['question_id']: q['public_question_id'] for q in read_jsonl(derived / 'question_metadata.jsonl')}
    repo = FactRepository(derived / 'financial_facts.sqlite', yaml.safe_load((ROOT/'config/concept_aliases.yaml').read_text(encoding='utf-8')), settings.search_top_k)
    client = OllamaProvider(settings, allow_live=True)
    rows = []
    try:
        for condition in 'ABCD':
            with TraceStore(folder / 'run_01' / condition) as store:
                runner = AnnotationRunner(settings, repo, load_rules(ROOT), prompts, client, store,
                                          trace_context={'experiment_kind': 'dev_engineering_probe'})
                for qid in ids:
                    raw = inputs[aliases[qid]]
                    question = QuestionInput(question_id=raw['question_id'], question=raw[settings.language], language=settings.language)
                    final = runner.run_question(question, source_question_id=qid, condition=condition, run_index=1, experiment_id=folder.name)
                    attempts = [r for r in store.read('attempts') if r['question_id'] == qid]
                    row = {'condition': condition, 'question_id': qid, 'first_tool_used': bool(attempts[0]['tool_calls']),
                           'attempts': len(attempts), 'final_status': final['final_status'],
                           'final_failure_codes': final['failure_codes'], 'judge_calls': sum(bool(r.get('judge_usage')) for r in attempts)}
                    rows.append(row)
                    print(json.dumps(row), flush=True)
    finally:
        client.close()
    if not (folder / 'summary.json').exists():
        write_new_json(folder / 'summary.json', {'scope': 'Two Dev questions only; not E2E evaluation', 'rows': rows})


if __name__ == '__main__':
    main()
