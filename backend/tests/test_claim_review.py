import pytest
from app.ideas.claim_review import review_items, reviewed_tickers, ClaimReview

IDEAS=[{'ticker':'NVDA','reasons':[{'text':'Revenue grew.','evidence_ids':['growth']}], 'risks':[{'text':'Supply risk.','evidence_ids':['risk']}]}]
OBS={'growth':{'id':'growth','ticker':'NVDA','text':'Revenue growth = 50%.','input_ids':['prior']},'prior':{'id':'prior','ticker':'NVDA','text':'Prior revenue 100 USD.'},'risk':{'id':'risk','ticker':'NVDA','text':'Supply availability could constrain growth.'},'uncited':{'id':'uncited','ticker':'NVDA','text':'An analyst expects stronger demand.'}}

def review():
    return {'actions':[{'ticker':'NVDA','supported':True}],'checks':[{'claim_id':'NVDA:reasons:0','supported':True,'quotes':[{'evidence_id':'growth','quote':'Revenue growth = 50%.'}]},{'claim_id':'NVDA:risks:0','supported':True,'quotes':[{'evidence_id':'risk','quote':'Supply availability could constrain growth.'}]}]}

def test_only_cited_evidence_and_dependencies_enter_claim_review():
    items=review_items(IDEAS,OBS)
    assert set(items[0]['evidence'])=={'growth','prior'}
    assert set(items[1]['evidence'])=={'risk'}
    assert reviewed_tickers(IDEAS,items,ClaimReview.model_validate(review()))['checks'][0]['supported']

@pytest.mark.parametrize('failure',['missing','duplicate','invented_quote','uncited_source','rejected','no_quote','missing_action','rejected_action','duplicate_action'])
def test_any_unsupported_claim_blocks_stock_approval(failure):
    value=review();c=value['checks'][0]
    if failure=='missing':value['checks'].pop()
    elif failure=='duplicate':value['checks'].append(c.copy())
    elif failure=='invented_quote':c['quotes'][0]['quote']='An invented statement.'
    elif failure=='uncited_source':c['quotes']=[{'evidence_id':'uncited','quote':OBS['uncited']['text']}]
    elif failure=='rejected':c['supported']=False
    elif failure=='missing_action':value['actions']=[]
    elif failure=='rejected_action':value['actions'][0]['supported']=False
    elif failure=='duplicate_action':value['actions'].append(value['actions'][0].copy())
    else:c['quotes']=[]
    assert not reviewed_tickers(IDEAS,review_items(IDEAS,OBS),ClaimReview.model_validate(value))['checks'][0]['supported']


def test_matching_words_in_an_unrelated_quote_do_not_support_analyst_cash_flow_claim():
    from app.ideas.claim_review import citation_topic_issue
    records=[{'text':'Growth depends on a small group of customers and constrained packaging supply.'}]
    assert citation_topic_issue('One analysis suggests revenue growth will not improve operating cash flow.',records)
    assert citation_topic_issue('Analysts consider the supply risk material.',records)
    assert citation_topic_issue('Growth depends on customer concentration and packaging supply.',records) is None
    assert citation_topic_issue('Operating cash flow increased.',[{'metric':'operating_cash_flow','text':'Operating cash flow: 50 USD.'}]) is None


@pytest.mark.parametrize('claim',[
    'Revenue shows a projected increase.',
    'Projections show operating margin improving.',
    'The forecast revenue is higher.',
    'This is not a forecast, but projected revenue improves.',
])
def test_historical_figures_cannot_be_relabelled_as_forecasts(claim):
    from app.ideas.claim_review import citation_topic_issue
    records=[{'metric':'revenue','text':'Revenue: 150 USD.','value':'150','period_type':'annual'},
             {'metric':'operating_margin','text':'Operating margin: 40 percent.','value':'40','period_type':'annual'}]
    assert 'Historical figures' in citation_topic_issue(claim,records)


def test_historical_warning_and_actual_guidance_are_not_blocked():
    from app.ideas.claim_review import citation_topic_issue
    records=[{'metric':'revenue','text':'Revenue: 150 USD.','value':'150','period_type':'annual'}]
    assert citation_topic_issue('Reported revenue is not a forecast.',records) is None
    assert citation_topic_issue('Management projected revenue growth.',[{'text':'Management projected revenue growth next year.'}]) is None


def test_information_does_not_require_action_but_still_requires_every_claim():
    value=review();value['actions']=[]
    result=reviewed_tickers(IDEAS,review_items(IDEAS,OBS),ClaimReview.model_validate(value),require_action=False)
    assert result['checks'][0]['supported']
    value['checks'][0]['supported']=False
    assert not reviewed_tickers(IDEAS,review_items(IDEAS,OBS),ClaimReview.model_validate(value),require_action=False)['checks'][0]['supported']


def test_information_coverage_fields_are_required_by_provider():
    from app.ideas.claim_review import InformationalClaimReview
    from app.providers.llm import response_schema
    schema=response_schema('ideas_claim_review',{'claims':[],'actions':[]},InformationalClaimReview)
    assert {'answers_question','remaining_question','checks','actions'}<=set(schema['required'])
