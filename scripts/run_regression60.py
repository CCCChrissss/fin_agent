"""Fixed 60-question regression entrypoint. Explicit plan/freeze/run stages."""
import argparse,json,sys
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from financial_annotation_harness.config import Settings,load_rules
from financial_annotation_harness.dataset import verify_derived
from financial_annotation_harness.facts import FactRepository
from financial_annotation_harness.governance import create_freeze,verify_freeze,project_hashes,environment_manifest
from financial_annotation_harness.io_utils import read_json,read_jsonl,file_hash,digest,write_new_json,timestamp
from financial_annotation_harness.ollama_provider import OllamaProvider
from financial_annotation_harness.runner import AnnotationRunner
from financial_annotation_harness.schemas import QuestionInput
from financial_annotation_harness.trace import TraceStore
from financial_annotation_harness.runtime_environment import environment_snapshot


def schedule(split):
    dev,test=split['development'],split['test']
    if len(dev)!=12 or len(set(dev))!=12 or len(test)!=48 or len(set(test))!=48 or set(dev)&set(test):
        raise ValueError('Expected disjoint 12 Development and 48 historical Test questions')
    return [{'partition':p,'run_index':r,'condition':c,'question_id':q}
            for p in ('development','test') for r in (1,2,3) for c in 'ABCD' for q in sorted(split[p])]


def verify_files(root,hashes):
    for path,expected in hashes.items():
        p=root/path
        if not p.is_file() or file_hash(p)!=expected:raise ValueError('Snapshot drift: '+path)


class ReleaseProvider(OllamaProvider):
    def __init__(self,settings,formats,**kwargs):
        self.formats=formats
        super().__init__(settings,**kwargs)
    def describe_request(self,role,seed):
        p=super().describe_request(role,seed)
        if role=='judge':p['format']=self.formats['online_judge_format']
        return p


def inputs():
    source=ROOT/'data/financial_qa_gold_dataset_v2.xlsx'
    derived=ROOT/'artifacts/derived'/file_hash(source)
    return verify_derived(source,derived),read_json(ROOT/'artifacts/dataset_split.json'),derived


def prepare(directory):
    source,split,_=inputs()
    candidate=read_json(ROOT/'outputs/freeze-readiness-20260917/candidate_settings.json')
    latest=read_json(ROOT/'outputs/dev-feedback-retry-v2/manifest.json')
    if project_hashes(ROOT)!=latest['project_hashes']:raise ValueError('Core changed after validated candidate')
    settings=Settings.model_validate(candidate['settings']);settings.require_live()
    if settings.model.model_dump()!=latest['settings']['model']:raise ValueError('Model configuration drift')
    if candidate['resolved_prompts']!=latest['prompts']:raise ValueError('Prompt drift')
    paths=[p for folder in ('scripts','config','experiments','tests') for p in (ROOT/folder).rglob('*')
           if p.is_file() and p.suffix in ('.py','.json','.yaml','.md') and '__pycache__' not in p.parts]
    paths += [ROOT/'artifacts/dataset_split.json',ROOT/settings.review_record,
              ROOT/'outputs/freeze-readiness-20260917/candidate_settings.json']
    snapshots={**project_hashes(ROOT),**{p.relative_to(ROOT).as_posix():file_hash(p) for p in paths}}
    plan={'schema_version':'1.0','study_kind':'complete_dataset_regression','held_out_claim':False,
          'historical_test_already_used':True,'settings':settings.model_dump(),
          'resolved_prompts':candidate['resolved_prompts'],'role_overrides':candidate['role_overrides'],
          'source_manifest_hash':digest(source),'split_hash':digest(split),'files':snapshots,
          'schedule':schedule(split),'created_at':timestamp(),'environment':environment_manifest(),
          'evaluation_policy':'Report Development 144 and historical Test 576 separately, plus clearly labeled combined 720 descriptive results. AI review is not human adjudication.'}
    directory.mkdir(parents=True,exist_ok=False)
    write_new_json(directory/'candidate.json',plan)
    return {'prepared':True,'question_runs':len(plan['schedule']),'development':144,'historical_test':576,'model_calls':0}


def validate_candidate(directory):
    c=read_json(directory/'candidate.json');verify_files(ROOT,c['files'])
    source,split,derived=inputs()
    if digest(source)!=c['source_manifest_hash'] or digest(split)!=c['split_hash'] or schedule(split)!=c['schedule']:
        raise ValueError('Dataset or schedule drift')
    if environment_manifest()!=c['environment']:raise ValueError('Python/package environment drift')
    return c,Settings.model_validate(c['settings']),source,split,derived


def seal(directory):
    c,settings,source,split,_=validate_candidate(directory)
    if (directory/'seal.json').exists() or (directory/'freeze.json').exists():raise FileExistsError('Preserve existing freeze')
    frozen=create_freeze(ROOT,source,split,settings,directory/'freeze.json',
         reviewer='Codex AI; user-authorized AI-assisted review',attestation='ai-reviewed-gold-and-rules')
    write_new_json(directory/'seal.json',{'candidate_sha256':file_hash(directory/'candidate.json'),
        'freeze_sha256':file_hash(directory/'freeze.json'),'study_kind':'complete_dataset_regression','held_out_claim':False})
    return {'frozen':True,'new_generation_calls':0,'path':str(directory/'freeze.json')}


def verify_release(directory):
    seal=read_json(directory/'seal.json')
    if file_hash(directory/'candidate.json')!=seal['candidate_sha256'] or file_hash(directory/'freeze.json')!=seal['freeze_sha256']:
        raise ValueError('Sealed configuration changed')
    c,settings,source,split,derived=validate_candidate(directory)
    frozen=read_json(directory/'freeze.json');verify_freeze(ROOT,source,split,settings,frozen)
    return c,settings,source,split,derived,frozen


def run(directory,output,resume=False):
    c,settings,source,split,derived,frozen=verify_release(directory)
    output=output.resolve()
    if not output.is_relative_to((ROOT/'outputs').resolve()):raise ValueError('Use a new workspace outputs directory')
    if output.exists()!=resume:raise ValueError('New output required, or explicit resume of an existing output')
    expected={'candidate_sha256':file_hash(directory/'candidate.json'),'freeze_sha256':file_hash(directory/'freeze.json'),
              'study_kind':'complete_dataset_regression','historical_test_already_used':True,'question_runs':720}
    if resume:
        if read_json(output/'release.json')!=expected:raise ValueError('Resume release mismatch')
    else:write_new_json(output/'release.json',expected)
    question_inputs={q['question_id']:q for q in read_jsonl(derived/'question_inputs.jsonl')}
    public_ids={q['question_id']:q['public_question_id'] for q in read_jsonl(derived/'question_metadata.jsonl')}
    repo=FactRepository(derived/'financial_facts.sqlite',yaml.safe_load((ROOT/'config/concept_aliases.yaml').read_text(encoding='utf-8')),settings.search_top_k)
    client=ReleaseProvider(settings,c['role_overrides'],allow_live=True)
    try:
        if client.runtime!=frozen['runtime'] or environment_snapshot()!=frozen['hardware']:raise ValueError('Runtime/hardware drift')
        client.calls=sum(e['event'] in ('generator_request','judge_request') for p in output.glob('*/run_*/[ABCD]/events.jsonl') for e in read_jsonl(p))
        for partition in ('development','test'):
            dest=output/partition
            manifest={'schema_version':'1.0','experiment_id':output.name+'-'+partition,'experiment_kind':'main',
               'study_stage':'frozen_complete_dataset_regression','held_out_claim':False,'historical_test_already_used':True,
               'mode':'live','partition':partition,'expected_runs':[{k:v for k,v in r.items() if k!='partition'} for r in c['schedule'] if r['partition']==partition],
               'settings':settings.model_dump(),'source_manifest_hash':digest(source),'split_hash':digest(split),
               'project_hashes':project_hashes(ROOT),'resolved_prompts':c['resolved_prompts'],'role_overrides':c['role_overrides'],
               'review_provenance':frozen['review_provenance'],'release':expected}
            if (dest/'manifest.json').exists():
                if read_json(dest/'manifest.json')!=manifest:raise ValueError('Partition manifest drift')
            else:write_new_json(dest/'manifest.json',manifest)
            for run_index in (1,2,3):
                for condition in 'ABCD':
                    with TraceStore(dest/f'run_{run_index:02d}'/condition) as trace:
                        runner=AnnotationRunner(settings,repo,load_rules(ROOT),c['resolved_prompts'],client,trace,
                            trace_context={'study_kind':'complete_dataset_regression','partition':partition,'held_out_claim':False})
                        for qid in sorted(split[partition]):
                            raw=question_inputs[public_ids[qid]]
                            q=QuestionInput(question_id=raw['question_id'],question=raw[settings.language],language=settings.language)
                            final=runner.run_question(q,source_question_id=qid,condition=condition,run_index=run_index,experiment_id=manifest['experiment_id'])
                            print(json.dumps({'partition':partition,'run':run_index,'condition':condition,'question':qid,'status':final['final_status'],'calls':client.calls}),flush=True)
                            recent=[a for a in trace.read('attempts') if a['question_id']==qid]
                            if any(a['runtime_error_type'] in ('CONNECTION_ERROR','MODEL_NOT_FOUND','CALL_BUDGET') for a in recent):raise RuntimeError('Infrastructure failure; preserve traces and stop')
        client.verify_identity();verify_release(directory)
    finally:client.close()
    for partition,n in [('development',144),('test',576)]:
        finals=[r for p in (output/partition).glob('run_*/[ABCD]/finals.jsonl') for r in read_jsonl(p)]
        if len(finals)!=n or len({(r['run_index'],r['condition'],r['question_id']) for r in finals})!=n:raise ValueError('Incomplete/duplicate results')
    return {'generation_complete':True,'question_runs':720,'evaluation_pending':True,'output':str(output)}


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','freeze','verify','run'])
    p.add_argument('--release',type=Path,default=ROOT/'outputs/regression60-release-v1')
    p.add_argument('--output',type=Path,default=ROOT/'outputs/regression60-v1')
    p.add_argument('--resume',action='store_true');p.add_argument('--live',action='store_true')
    a=p.parse_args()
    if a.action=='prepare':result=prepare(a.release)
    elif a.action=='freeze':result=seal(a.release)
    elif a.action=='verify':verify_release(a.release);result={'valid':True,'question_runs':720,'model_calls':0}
    else:
        if not a.live:raise ValueError('Explicit --live required for model generation')
        result=run(a.release,a.output,a.resume)
    print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
