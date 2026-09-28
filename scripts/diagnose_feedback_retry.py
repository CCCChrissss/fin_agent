"""Gemma-only synthetic Dev feedback/retry diagnostic using unchanged D runner."""
import argparse
import copy
import html
import json
from pathlib import Path
import sys
import yaml
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'scripts'))
from financial_annotation_harness.config import Settings,load_rules
from financial_annotation_harness.facts import FactRepository
from financial_annotation_harness.governance import project_hashes
from financial_annotation_harness.io_utils import canonical,digest,file_hash,read_json,read_jsonl,write_new_json
from financial_annotation_harness.model_client import Turn
from financial_annotation_harness.runner import AnnotationRunner
from financial_annotation_harness.schemas import QuestionInput
from financial_annotation_harness.trace import TraceStore
from financial_annotation_harness.validators import answer_equal,normalize_unit
from run_dev_prompt_v2 import CandidateProvider
from diagnose_dev_judge import immutable

SOURCE=ROOT/'outputs/dev-judge-diagnostic-v1'
BASE=ROOT/'outputs/dev-prompt-v4/full-dev-v4'
OUT=ROOT/'outputs/dev-feedback-retry-v1'


class ReplayInitialJudge:
    """Only the exact saved initial Judge request is replayed; all later calls live."""
    def __init__(self,live,messages,response):
        self.live,self.messages,self.response=live,messages,response
        self.replayed=False
    def __getattr__(self,name):return getattr(self.live,name)
    def complete(self,messages,tools,*,role,seed):
        if not self.replayed:
            if role!='judge' or tools or messages!=self.messages:
                raise ValueError('Replay input differs from original diagnostic Judge request')
            self.replayed=True
            response=copy.deepcopy(self.response)
            response['runtime']={**response.get('runtime',{}),'diagnostic_replay':True,'new_inference':False}
            return Turn(**response)
        return self.live.complete(messages,tools,role=role,seed=seed)


class SeededRunner(AnnotationRunner):
    def __init__(self,*args,payload,**kwargs):
        super().__init__(*args,**kwargs);self.payload=copy.deepcopy(payload)
    def _generate(self,messages,question,identity,attempt,turns,calls,retrieved,record):
        if attempt!=1:
            return super()._generate(messages,question,identity,attempt,turns,calls,retrieved,record)
        # Explicit diagnostic prefill, not a fabricated historical Generator/tool call.
        candidates=self.payload['candidate_financial_facts']
        retrieved.update({f['fact_id']:copy.deepcopy(f) for f in candidates})
        messages.append({'role':'user','content':canonical({'available_financial_facts':candidates})})
        raw=canonical(self.payload['generated_structured_artifact'])
        messages.append({'role':'assistant','content':raw})
        self.traces.append('events',{**identity,'attempt':attempt,'event':'synthetic_diagnostic_prefill',
            'payload_hash':digest(self.payload),'new_generator_inference':False,'candidate_fact_ids':list(retrieved)})
        record['synthetic_diagnostic_prefill']=True
        return raw


def analyze(out,cases,controls):
    rows=[]
    for case in cases:
        folder=out/case['case_id']
        with TraceStore(folder) as trace:
            attempts=trace.read('attempts'); finals=trace.read('finals');events=trace.read('events')
        assert len(finals)==1 and len(attempts)<=3
        final=finals[0];a=final.get('artifact') or {};reference=controls[case['source_question_id']]['payload']['generated_structured_artifact']
        eligible=[r for r in attempts if r['attempt']>1]
        selected=lambda x:{e['fact_id'] for e in x.get('selected_evidence',[])}
        checks={'answer_matches_reference':answer_equal(a.get('answer'),reference['answer'],reference['unit']),
                'unit_matches_reference':normalize_unit(a.get('unit',''))==normalize_unit(reference['unit']),
                'evidence_matches_reference':selected(a)==selected(reference),
                'question_type_matches_reference':a.get('question_type')==reference['question_type']}
        row={'case_id':case['case_id'],'source_question_id':case['source_question_id'],'category':case['category'],
             'final_status':final['final_status'],'retries_used':len(eligible),'checks':checks,
             'offline_semantic_inspection':'pending','attempts':[{'attempt':r['attempt'],'status':r['final_status'],
             'failure_codes':r['failure_codes'],'runtime_error_type':r['runtime_error_type'],
             'artifact':r['artifact'],'validator_results':r['validator_results'],'judge_result':r['judge_result']} for r in attempts],
             'new_generator_requests':sum(e['event']=='generator_request' for e in events),
             'new_judge_requests':sum(e['event']=='judge_request' and e['attempt']>1 for e in events),
             'cached_initial_judge':sum(e['event']=='judge_response' and e['response']['runtime'].get('diagnostic_replay',False) for e in events),
             'new_deterministic_failure_attempts':sum(any(v['status']!='PASS' for v in r['validator_results'].values()) for r in eligible),
             'latency_ms':sum(r['latency_ms'] for r in eligible)}
        rows.append(row)
    summary={'scope':'Synthetic feedback/retry diagnostic, not main D accuracy','case_count':len(rows),
             'gate_accepted':sum(r['final_status']=='ACCEPTED' for r in rows),
             'offline_reference_checks_pass':sum(all(r['checks'].values()) for r in rows),
             'new_generator_requests':sum(r['new_generator_requests'] for r in rows),
             'new_judge_requests':sum(r['new_judge_requests'] for r in rows),
             'cached_initial_judge':sum(r['cached_initial_judge'] for r in rows),
             'cases_with_new_deterministic_failures':sum(r['new_deterministic_failure_attempts']>0 for r in rows),
             'human_review_completed':False,'rows':rows}
    write_new_json(out/'summary.json',summary)
    return summary


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');args=parser.parse_args()
    source_manifest=read_json(SOURCE/'manifest.json')
    settings=Settings.model_validate(source_manifest['settings']['model_1'])
    settings.max_live_calls=270
    assert settings.model.judge_model==settings.model.generator_model
    old=read_json(BASE/'manifest.json');prompts=old['resolved_prompts']
    cases=[c for c in read_jsonl(SOURCE/'cases.jsonl') if not c['expected_pass'] and c['deterministic_pass']]
    controls={c['source_question_id']:c for c in read_jsonl(SOURCE/'cases.jsonl') if c['expected_pass']}
    assert len(cases)==9
    split=read_json(ROOT/'artifacts/dataset_split.json')
    assert {c['source_question_id'] for c in cases}<=set(split['development'])
    source=ROOT/'data/financial_qa_gold_dataset_v2.xlsx';source_hash=file_hash(source)
    assert source_hash==source_manifest['source_sha256']
    assert project_hashes(ROOT)==source_manifest['project_hashes']
    inputs={str(p.relative_to(ROOT)):file_hash(p) for folder in (SOURCE,BASE) for p in folder.rglob('*') if p.is_file()}
    manifest={'kind':'synthetic_dev_feedback_retry','settings':settings.model_dump(),'prompts':prompts,
              'project_hashes':project_hashes(ROOT),'source_sha256':source_hash,'input_hashes':inputs,
              'script_sha256':file_hash(Path(__file__)),'case_ids':[c['case_id'] for c in cases],
              'policy':'Seed corrupted draft + visible facts; replay exact previous initial Gemma Judge; unchanged D runner attempts 2/3 live. Synthetic prefill is not original Generator history.',
              'gold_visible_online':False,'test_executed':False,'max_retries':2,
              'evaluation':'Gate acceptance separate from offline reference checks and AI semantic inspection.'}
    OUT.mkdir(exist_ok=True);immutable(OUT/'manifest.json',manifest)
    print(json.dumps({'cases':len(cases),'max_live_retries':18,'initial_judge_replayed':9,'live':args.live}),flush=True)
    if not args.live:return
    repo=FactRepository(ROOT/'artifacts/derived'/source_hash/'financial_facts.sqlite', yaml.safe_load((ROOT/'config/concept_aliases.yaml').read_text(encoding='utf-8')), settings.search_top_k)
    live=CandidateProvider(settings,allow_live=True)
    try:
        immutable(OUT/'runtime.json',live.runtime)
        for i,case in enumerate(cases,1):
            key=case['case_id'];request=read_json(SOURCE/'model_1'/(key+'.request.json'))
            response=read_json(SOURCE/'model_1'/(key+'.json'))
            assert response['verdict']['overall_pass'] is False
            client=ReplayInitialJudge(live,request['messages'],response['raw_response'])
            p=case['payload'];q=QuestionInput(question_id=p['generated_structured_artifact']['question_id'],question=p['original_question'],language='zh')
            with TraceStore(OUT/key) as store:
                runner=SeededRunner(settings,repo,load_rules(ROOT),prompts,client,store,payload=p,
                    trace_context={'experiment_kind':'synthetic_diagnostic','case_id':key,'initial_judge_source_sha256':file_hash(SOURCE/'model_1'/(key+'.json'))})
                final=runner.run_question(q,source_question_id=case['source_question_id'],condition='D',run_index=1,experiment_id=OUT.name)
            print(json.dumps({'completed':i,'total':9,'case':key,'status':final['final_status'],'attempt':final['attempt'],'live_calls':live.calls}),flush=True)
        live.verify_identity()
    finally:live.close()
    assert file_hash(source)==source_hash and project_hashes(ROOT)==manifest['project_hashes']
    assert all(file_hash(ROOT/p)==h for p,h in inputs.items())
    if not (OUT/'summary.json').exists():
        summary=analyze(OUT,cases,controls)
        print(json.dumps({k:v for k,v in summary.items() if k!='rows'}),flush=True)
    immutable(OUT/'verification.json',{'old_outputs_unchanged':True,'gold_unchanged':True,'core_unchanged':True})

if __name__=='__main__':main()
