import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def load_candidates():
    path = ROOT / 'scripts/dev_prompt_candidates.py'
    assert path.exists(), 'Versioned prompt candidate loader is required'
    sys.path.insert(0, str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('candidate', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_candidate_preserves_common_contract_baseline_and_online_judge():
    m = load_candidates()
    original = {'baseline': 'A', 'contract': 'shared', 'workflow': 'B workflow', 'judge': 'D judge'}
    revised = m.generator_prompts(original)
    assert revised['baseline'] == 'A'
    assert revised['contract'] == 'shared'
    assert revised['judge'] == 'D judge'
    assert '| 項目 | 2040 | 2041 |' in revised['workflow']
    assert original['workflow'] == 'B workflow'


def test_judge_prompt_changes_system_only_and_preserves_fresh_payload():
    m = load_candidates()
    messages = [{'role': 'system', 'content': 'original rubric'},
                {'role': 'user', 'content': '{"original_question":"Q","generated_structured_artifact":{}}'}]
    revised = m.judge_prompt(messages)
    assert len(revised) == 2
    assert revised[1] == messages[1]
    assert messages[0]['content'] == 'original rubric'
    assert 'semantic_parse.filter' in revised[0]['content']
