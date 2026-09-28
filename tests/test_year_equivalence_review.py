import copy
from financial_annotation_harness.schemas import Annotation
from financial_annotation_harness.validators import YearValidator, ValidationContext


def check(specimen, rules, raw):
    repo, q, _, _ = specimen
    return YearValidator().validate(Annotation.model_validate(raw), ValidationContext(q.question_id, q.question, repo, rules))


def test_roc_semantic_years_equal_gregorian_without_mutating(specimen, rules):
    raw = copy.deepcopy(specimen[2])
    for t in raw['semantic_parse']['time']:
        t['fiscal_year'] -= 1911
    original = copy.deepcopy(raw)
    assert check(specimen, rules, raw).status == 'PASS'
    assert raw == original


def test_equivalent_duplicate_years_still_fail(specimen, rules):
    raw = copy.deepcopy(specimen[2])
    duplicate = copy.deepcopy(raw['semantic_parse']['time'][0])
    duplicate['fiscal_year'] -= 1911
    raw['semantic_parse']['time'].append(duplicate)
    assert any(i.rule_id == 'TIME-04' for i in check(specimen, rules, raw).issues)


def test_roc_year_does_not_hide_wrong_period(specimen, rules):
    raw = copy.deepcopy(specimen[2])
    for t in raw['semantic_parse']['time']:
        t['fiscal_year'] -= 1911
    raw['semantic_parse']['time'][0]['period_end'] = '2020-12-31'
    assert any(i.rule_id == 'TIME-02' for i in check(specimen, rules, raw).issues)
