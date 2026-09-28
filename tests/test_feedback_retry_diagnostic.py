import copy
import importlib.util
import json
from dataclasses import asdict
from pathlib import Path
from financial_annotation_harness.config import Settings
from financial_annotation_harness.demo import judge_pass
from financial_annotation_harness.facts import tool_fact
from financial_annotation_harness.judge import judge_messages
from financial_annotation_harness.model_client import ScriptedClient, Turn
from financial_annotation_harness.trace import TraceStore


def module():
    path=Path(__file__).resolve().parents[1]/'scripts/diagnose_feedback_retry.py'
    assert path.exists(), 'Feedback retry diagnostic not implemented'
    spec=importlib.util.spec_from_file_location('diagnose_feedback_retry',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def failure():
    return Turn(content=json.dumps({'semantic_parse_pass':False,'concept_pass':True,'evidence_pass':True,'golden_context_pass':True,'overall_pass':False,'failure_codes':['SEMANTIC_PARSE_ERROR'],'issues':[{'failure_code':'SEMANTIC_PARSE_ERROR','rule_id':'concept','field_path':'semantic_parse.concept','observed_value':'wrong','expected_constraint':'requested concept','recommended_correction':'Fix concept.'}],'feedback':'Fix concept.'}))


def test_seeded_diagnostic_uses_saved_feedback_and_two_live_retries_max(tmp_path,specimen,rules,prompts):
    m=module();repo,q,good,_=specimen
    bad=copy.deepcopy(good);bad['semantic_parse']['concept']=['wrong']
    facts=[tool_fact(repo.get(fid)) for fid in bad['retrieved_fact_ids']]
    payload={'original_question':q.question,'generated_structured_artifact':bad,'candidate_financial_facts':facts,'selected_financial_facts':facts}
    expected=judge_messages(q.question,bad,facts,facts,prompts['judge'])
    live=ScriptedClient([Turn(content=json.dumps(bad)),failure(),Turn(content=json.dumps(bad)),failure()])
    client=m.ReplayInitialJudge(live,expected,asdict(failure()))
    with TraceStore(tmp_path/'trace') as store:
        runner=m.SeededRunner(Settings(),repo,rules,prompts,client,store,payload=payload)
        final=runner.run_question(q,source_question_id='SYN',condition='D',run_index=1,experiment_id='diagnostic')
        attempts=store.read('attempts')
    assert final['final_status']=='FAILED' and final['attempt']==3
    assert len(attempts)==3 and len(live.requests)==4 and client.replayed
    assert [r['role'] for r in live.requests]==['generator','judge','generator','judge']
    assert 'Fix concept.' in live.requests[0]['messages'][-1]['content']
    assert all(len(r['messages'])==2 for r in live.requests if r['role']=='judge')


def test_replay_refuses_different_judge_input():
    import pytest
    m=module();live=ScriptedClient([])
    client=m.ReplayInitialJudge(live,[{'role':'user','content':'expected'}],asdict(failure()))
    with pytest.raises(ValueError,match='Replay input differs'):
        client.complete([{'role':'user','content':'changed'}],[],role='judge',seed=1)
    assert not live.requests
