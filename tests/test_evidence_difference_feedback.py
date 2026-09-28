import copy
import pytest
from financial_annotation_harness.schemas import Annotation
from financial_annotation_harness.validators import EvidenceValidator,ValidationContext

@pytest.mark.parametrize('retrieved,selected', [(['a','b','c'],['a','b']),(['a'],['a','b']),(['a','a'],['a']),(['a'],['a','a']),([],[]),(['a'],['a']),(['b','a'],['a','b'])])
def test_evid01_exact_differences_and_unchanged_acceptance(specimen,rules,retrieved,selected):
    repo,q,raw,_=specimen
    a=copy.deepcopy(raw)
    a['retrieved_fact_ids']=retrieved
    a['selected_evidence']=[{**raw['selected_evidence'][0],'fact_id':fid,'variable_name':'v'+str(i)} for i,fid in enumerate(selected)]
    before=copy.deepcopy(a)
    result=EvidenceValidator().validate(Annotation.model_validate(a),ValidationContext(q.question_id,q.question,repo,rules))
    issues=[i for i in result.issues if i.rule_id=='EVID-01']
    should_fail=not selected or len(selected)!=len(set(selected)) or set(selected)!=set(retrieved) or len(retrieved)!=len(set(retrieved))
    assert bool(issues)==bool(should_fail)
    assert a==before
    if issues:
        details=issues[0].observed_value
        assert isinstance(details,dict),'Feedback must expose both fields, not only selected IDs'
        assert details['retrieved_fact_ids']==retrieved
        assert details['selected_evidence_fact_ids']==selected
        assert details['only_in_retrieved_fact_ids']==sorted(set(retrieved)-set(selected))
        assert details['only_in_selected_evidence']==sorted(set(selected)-set(retrieved))
        assert details['duplicate_retrieved_fact_ids']==sorted(x for x in set(retrieved) if retrieved.count(x)>1)
        assert details['duplicate_selected_evidence_fact_ids']==sorted(x for x in set(selected) if selected.count(x)>1)
        assert result.validator_version=='1.3'
