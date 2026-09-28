"""Dev-only prompt assembly. No Gold access and no changes to core experiment controls."""
import copy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def generator_prompts(original):
    from pilot_dev_workflow import WORKFLOW_REMINDER
    result = dict(original)
    example = (ROOT / 'experiments/dev_prompt_v2/workflow_example.md').read_text(encoding='utf-8')
    result['workflow'] += '\n' + WORKFLOW_REMINDER + '\n' + example
    return result


def judge_prompt(messages):
    from probe_dev_judge import CHECKLIST
    result = copy.deepcopy(messages)
    example = (ROOT / 'experiments/dev_prompt_v2/judge_contrast.md').read_text(encoding='utf-8')
    result[0]['content'] += '\n' + CHECKLIST + '\n' + example
    return result
