import pytest
from financial_annotation_harness.config import Settings

def test_one_run_requires_explicit_protocol_amendment():
    assert Settings(protocol_version='1.1',runs_per_condition=1).runs_per_condition==1
    assert Settings().runs_per_condition==3
    with pytest.raises(ValueError):Settings(protocol_version='1.0',runs_per_condition=1)
    with pytest.raises(ValueError):Settings(protocol_version='1.1',runs_per_condition=3)

def test_one_run_schedule_has_240_unique_runs():
    import importlib.util
    from pathlib import Path
    p=Path(__file__).resolve().parents[1]/'scripts/run_regression60_once.py'
    assert p.exists(),'One-run entrypoint missing'
    spec=importlib.util.spec_from_file_location('once',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    plan=m.schedule({'development':[f'D{i}' for i in range(12)],'test':[f'T{i}' for i in range(48)]})
    assert len(plan)==240 and {r['run_index'] for r in plan}=={1}
    assert sum(r['partition']=='development' for r in plan)==48
    assert sum(r['partition']=='test' for r in plan)==192

def test_single_run_evaluation_has_no_between_run_sd(tmp_path,rules,prompts):
    import json,shutil
    from financial_annotation_harness.demo import run_demo,demo_data
    from financial_annotation_harness.evaluation import evaluate_experiment
    from financial_annotation_harness.facts import FactRepository
    demo=tmp_path/'demo';run_demo(demo,rules,prompts)
    single=tmp_path/'single';single.mkdir()
    shutil.copytree(demo/'run_01',single/'run_01')
    manifest=json.loads((demo/'manifest.json').read_text(encoding='utf-8'))
    manifest['expected_runs']=[r for r in manifest['expected_runs'] if r['run_index']==1]
    (single/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    _,_,q,_,gold=demo_data()
    result=evaluate_experiment(single,[gold],[q.model_dump()],FactRepository(demo/'financial_facts.sqlite'),rules,single/'eval')
    assert result['observed_question_runs']==4
    for metrics in result['metrics'].values():
        assert len(metrics['answer_accuracy']['per_run'])==1
        assert metrics['answer_accuracy']['sample_sd'] is None
