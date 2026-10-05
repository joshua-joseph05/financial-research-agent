import pytest
from app.agent.attribution import reported_financial_findings
from app.agent.graph import structural_check


def record(**changes):
    return {'id':'value1','source_id':'filing','ticker':'X','metric':'operating_income','value':'60.50','unit':'USD','period_type':'annual','period_end':'2025-06-30','period':'2025-06-30','scope':'company','text':'Reported operating income 60.50 USD.',**changes}


def test_exact_value_unit_and_period_are_preserved_without_fiscal_year_guess():
    r=record();finding=reported_financial_findings({'value1':r})[0]
    assert finding['text']=='X reported operating income of 60.50 USD for the annual period ending 2025-06-30.'
    assert finding['evidence_ids']==['value1']
    assert structural_check(finding,{'observations':{'value1':r},'sources':{'filing':{}},'plan':{}},True) is None


@pytest.mark.parametrize('changes',[{'value':'NaN'},{'value':'Infinity'},{'scope':'segment'},{'period_type':'quarterly'},{'period_end':None},{'source_id':''},{'metric':'forecast'},{'operation':'growth'}])
def test_ineligible_records_are_not_canonical_facts(changes):
    assert reported_financial_findings({'value1':record(**changes)})==[]


def test_missing_source_still_blocks_exact_rendered_fact():
    r=record();finding=reported_financial_findings({'value1':r})[0]
    assert structural_check(finding,{'observations':{'value1':r},'sources':{},'plan':{}},True)=='Evidence has no source'


def test_direct_numeric_review_requires_all_declared_company_coverage():
    from app.agent.coverage import numeric_review_ready
    plan={'evidence_requirements':['financial_values'],'coverage_targets':[{'ticker':'X','needs':['financial_values']}]}
    obs={'income':record(id='income'),'revenue':record(id='revenue',metric='revenue')}
    assert numeric_review_ready(plan,obs,list(obs))
    assert not numeric_review_ready(plan,{'income':obs['income']},['income'])
    assert not numeric_review_ready({**plan,'evidence_requirements':['financial_values','filing_passages']},obs,list(obs))
    assert not numeric_review_ready({**plan,'coverage_targets':[]},obs,list(obs))
    assert not numeric_review_ready(plan,obs,['missing'])


def test_calculation_review_path_requires_calculation_and_preserves_historical_research():
    from app.agent.coverage import numeric_review_ready
    plan={'answer_type':'descriptive','evidence_requirements':['financial_values','calculated_metrics'],'coverage_targets':[{'ticker':'X','needs':['financial_values','calculated_metrics']}]}
    obs={'income':record(id='income'),'revenue':record(id='revenue',metric='revenue')}
    assert not numeric_review_ready(plan,obs,list(obs))
    obs['calc']={'id':'calc','ticker':'X','operation':'operating_margin','input_ids':['income','revenue'],'period':'2025-06-30','value':'100'}
    assert numeric_review_ready(plan,obs,list(obs))
    assert not numeric_review_ready({**plan,'answer_type':'historical_explanation'},obs,list(obs))
