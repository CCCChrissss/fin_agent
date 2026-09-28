import importlib.util
from pathlib import Path
import pytest


def module():
    p=Path(__file__).resolve().parents[1]/'scripts/run_regression60.py'
    assert p.exists(), 'Fixed regression entrypoint not implemented'
    spec=importlib.util.spec_from_file_location('run_regression60',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def test_plan_preserves_partition_and_720_unique_runs():
    m=module();split={'development':[f'D{i}' for i in range(12)],'test':[f'T{i}' for i in range(48)]}
    plan=m.schedule(split)
    assert len(plan)==720
    assert sum(r['partition']=='development' for r in plan)==144
    assert sum(r['partition']=='test' for r in plan)==576
    assert len({(r['run_index'],r['condition'],r['question_id']) for r in plan})==720
    assert {r['condition'] for r in plan}==set('ABCD')

def test_plan_rejects_overlap_or_duplicate_ids():
    m=module();split={'development':[str(i) for i in range(12)],'test':[str(i) for i in range(48)]}
    with pytest.raises(ValueError):m.schedule(split)

def test_snapshot_detects_script_drift_before_any_live_call(tmp_path):
    m=module();p=tmp_path/'entry.py';p.write_text('original')
    snapshot={'entry.py':m.file_hash(p)}
    m.verify_files(tmp_path,snapshot)
    p.write_text('changed')
    with pytest.raises(ValueError,match='Snapshot drift'):m.verify_files(tmp_path,snapshot)

def test_saved_role_formats_preserve_generator_prompt_only():
    m=module();obj=object.__new__(m.ReleaseProvider)
    from financial_annotation_harness.config import Settings
    obj.settings=Settings();obj.formats={'online_judge_format':{'type':'object'}}
    assert 'format' not in obj.describe_request('generator',1)
    assert obj.describe_request('judge',1)['format']=={'type':'object'}
