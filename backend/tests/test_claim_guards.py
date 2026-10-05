import pytest
from app.agent.claim_guards import passage_claim_issue
from app.agent.graph import structural_check
from app.ideas.claim_review import citation_topic_issue

RISK='Infrastructure investment may increase depreciation and operating costs.'

@pytest.mark.parametrize('word',['necessary','required','essential','mandatory','unavoidable'])
def test_added_necessity_is_rejected(word):
    assert passage_claim_issue(f'Costs may rise due to {word} infrastructure investments.',[{'text':RISK}])


def test_sourced_necessity_and_negation_are_preserved():
    assert passage_claim_issue('Infrastructure investment is required.',[{'text':'Infrastructure investment is necessary.'}]) is None
    assert passage_claim_issue('Infrastructure investment is not necessary.',[{'text':'No additional infrastructure investment is necessary.'}]) is None
    assert passage_claim_issue('Investment may increase costs.',[{'text':RISK}]) is None
    assert passage_claim_issue('Investment is required.',[{'text':'Investment is not necessary.'}])


@pytest.mark.parametrize('text',[
    'The company earns money from cloud services and software subscriptions.',
    'The company generates revenue through insurance premiums.',
    'The company makes money by selling aircraft engines.',
])
def test_unrelated_risk_cannot_support_business_description(text):
    assert passage_claim_issue(text,[{'text':RISK}])
    assert citation_topic_issue(text,[{'text':RISK}])


def test_business_description_can_be_supported_in_any_section():
    assert passage_claim_issue('It earns money through software subscriptions.',[{'section':'risks','text':'We depend on software subscription revenue.'}]) is None


def test_research_structural_check_applies_guard_when_enabled():
    state={'plan':{},'sources':{'s':{}},'observations':{'passage:x':{'id':'passage:x','source_id':'s','ticker':'X','text':RISK}}}
    finding={'id':'claim','text':'The company earns money from cloud services.','evidence_ids':['passage:x'],'scope':'unknown','explains_change':False}
    assert 'business activity' in structural_check(finding,state,strict_claims=True)
    assert structural_check(finding,state) is None


def test_descriptive_business_report_does_not_imply_a_missing_historical_comparison():
    from app.agent.attribution import render_findings
    finding={'text':'The company earns money from subscriptions.','evidence_ids':['passage:b'],'kind':'fact','scope':'unknown'}
    obs={'passage:b':{'ticker':'X'},'one':{'ticker':'X','period_end':'2025-12-31'},'two':{'ticker':'X','period_end':'2024-12-31'}}
    descriptive=render_findings([finding],obs,historical_explanation=False)
    assert descriptive=='Source-reported: The company earns money from subscriptions.'
    historical=render_findings([finding],obs,historical_explanation=True)
    assert 'Background only' in historical and 'Comparison period unverified' in historical


def test_wrong_company_claim_rejected_even_when_business_words_overlap():
    from app.agent.claim_guards import issuer_claim_issue
    names={'MSFT':'Microsoft Corporation','NVDA':'NVIDIA Corporation'}
    records=[{'ticker':'NVDA','text':'NVIDIA sells accelerated computing systems and software.'}]
    assert issuer_claim_issue('Microsoft earns money from software subscriptions.', records, names)
    assert issuer_claim_issue('NVDA sells computing systems.', records, names) is None
    assert issuer_claim_issue('The company sells software.', records, names) is None


def test_cross_company_passage_and_multi_issuer_comparison_allowed():
    from app.agent.claim_guards import issuer_claim_issue
    names={'MSFT':'Microsoft','NVDA':'NVIDIA'}
    assert issuer_claim_issue('Microsoft buys NVIDIA products.', [{'ticker':'NVDA','text':'Microsoft buys our products.'}], names) is None
    assert issuer_claim_issue('Microsoft and NVIDIA sell software.', [{'ticker':'NVDA','text':'Software'},{'ticker':'MSFT','text':'Software'}], names) is None


@pytest.mark.parametrize('text',[
    'The provided evidence does not contain NVIDIA data.',
    'Available data lacks business descriptions.',
    'The collected sources contain no financial information.',
])
def test_retrieval_absence_is_not_a_company_fact(text):
    from app.agent.claim_guards import coverage_claim_issue
    assert coverage_claim_issue(text)


def test_source_risk_is_not_confused_with_retrieval_coverage():
    from app.agent.claim_guards import coverage_claim_issue
    assert coverage_claim_issue('Microsoft does not guarantee future revenue growth.') is None


def test_wrong_issuer_and_coverage_checks_override_model_approval():
    state={'plan':{},'sources':{'s':{}},'observations':{'passage:x':{'id':'passage:x','source_id':'s','ticker':'NVDA','text':'NVIDIA sells software.'}}}
    finding={'id':'claim','text':'Microsoft earns money from software.','evidence_ids':['passage:x'],'scope':'unknown','explains_change':False}
    assert 'another issuer' in structural_check(finding,state,True,{'MSFT':'Microsoft','NVDA':'NVIDIA'})
    finding['text']='The provided evidence does not contain NVIDIA data.'
    assert 'Retrieval coverage' in structural_check(finding,state,True)


@pytest.mark.parametrize('text',[
    'Higher revenue and higher net income do not establish the cash balance.',
    'Revenue grew and net income increased.',
    'Net profit rose while revenue declined.',
])
def test_each_asserted_financial_trend_needs_own_citations(text):
    from app.agent.claim_guards import financial_trend_citation_issue
    revenue={'metric':'revenue','text':'Revenue was 300 and then 315.'}
    income={'metric':'net_income','text':'Net income was 75 and then 76.'}
    assert 'net_income' in financial_trend_citation_issue(text,[revenue])
    assert financial_trend_citation_issue(text,[revenue,income]) is None
    assert citation_topic_issue(text,[revenue])


def test_unknown_metric_and_supported_passage_are_not_rejected():
    from app.agent.claim_guards import financial_trend_citation_issue
    assert financial_trend_citation_issue('Higher revenue does not establish net income or cash balances.',
        [{'metric':'revenue','text':'Revenue rose.'}]) is None
    assert financial_trend_citation_issue('Net income increased.',
        [{'text':'Net income increased after lower expenses.'}]) is None


def test_uncited_observations_cannot_supply_a_missing_trend():
    state={'plan':{},'sources':{'s':{}},'observations':{
        'r':{'id':'r','source_id':'s','ticker':'X','metric':'revenue','text':'Revenue rose.'},
        'n':{'id':'n','source_id':'s','ticker':'X','metric':'net_income','text':'Net income rose.'}}}
    finding={'text':'Higher revenue and higher net income do not establish cash balances.',
             'evidence_ids':['r'],'explains_change':False}
    assert 'net_income' in structural_check(finding,state,True)
    finding['evidence_ids'].append('n')
    assert structural_check(finding,state,True) is None


def test_reported_multi_metric_reference_needs_both_metrics():
    from app.agent.claim_guards import financial_trend_citation_issue
    text="The reported revenue and net income figures alone do not establish cash balances."
    assert financial_trend_citation_issue(text,[{'metric':'revenue','text':'Revenue'}])
    assert financial_trend_citation_issue(text,[{'metric':'revenue','text':'Revenue'},
        {'metric':'net_income','text':'Net income'}]) is None
