from app.agent.presentation import beginner_guide
from app.schemas import Evidence


def margin(id, value, end, start):
    return Evidence(id=id, source_id='s', ticker='TEST', text='Operating margin', metric='operating_margin', operation='operating_margin', value=value, unit='percent', period=end, period_start=start, period_end=end, period_type='annual').model_dump()


def finding(id):
    return {'id': 'finding_'+id, 'text': 'Operating margin.', 'evidence_ids': [id]}


def test_explains_per_hundred_and_percentage_point_change_with_citations():
    rows=[margin('a','20.0000','2024-12-31','2024-01-01'),margin('b','25.0000','2025-12-31','2025-01-01')]
    guide=beginner_guide([finding('a'),finding('b')],rows,True)
    assert '$100' in guide.explanations[0].explanation
    assert '$25' in guide.explanations[0].explanation
    assert '5 percentage points' in guide.overview
    assert guide.explanations[0].evidence_ids==['a','b']
    assert len(guide.explanations[0].figures)==2
    assert any(term.term=='Percentage points' for term in guide.glossary)


def test_does_not_invent_causes_or_turn_partial_into_complete():
    guide=beginner_guide([finding('a')],[margin('a','20','2024-12-31','2024-01-01')],False)
    assert 'partial answer' in guide.status
    assert 'does not by itself explain the cause' in guide.explanations[0].why_it_matters
    assert '2025' not in guide.overview


def test_negative_margin_explains_operating_loss():
    guide=beginner_guide([finding('a')],[margin('a','-10','2024-12-31','2024-01-01')],True)
    assert '$10 was lost' in guide.explanations[0].explanation


def test_empty_report_and_demo_are_clear():
    guide=beginner_guide([],[],False,True)
    assert 'fictional' in guide.status and 'did not produce verified findings' in guide.status
    assert not guide.explanations


def test_segment_risk_qualifier_preserved():
    fact={'id':'f','text':'Supply chain delays could limit deliveries.','evidence_ids':['p'],'scope':'segment','segment':'Hardware','kind':'risk','fiscal_years':[2025]}
    guide=beginner_guide([fact],[{'id':'p'}],True)
    assert 'only to Hardware' in guide.explanations[0].explanation
    assert 'not something certain' in guide.explanations[0].why_it_matters
    assert any(g.term=='Supply chain' for g in guide.glossary)


def test_large_financial_values_explained_in_billions():
    e=Evidence(id='a',source_id='s',ticker='TEST',text='Annual revenue',value='45000000000',metric='revenue',unit='USD',period_end='2025-12-31').model_dump()
    guide=beginner_guide([{'id':'f','text':'Revenue was 45000000000 USD.','evidence_ids':['a']}],[e],True)
    assert '$45 billion' in guide.overview
    assert 'do not automatically mean rising profit' in guide.explanations[0].why_it_matters


def test_margin_change_finding_explains_verified_input_margins():
    rows=[margin('a','20','2024-12-31','2024-01-01'),margin('b','25','2025-12-31','2025-01-01')]
    change=Evidence(id='c',source_id='s',ticker='TEST',text='Margin increased',operation='margin_change',value='5',input_ids=['b','a']).model_dump()
    guide=beginner_guide([finding('c')],rows+[change],True)
    assert len(guide.explanations)==1
    assert 'for every $100 of sales' in guide.explanations[0].explanation
    assert '5 percentage points' in guide.overview


def test_failed_search_does_not_blame_user_or_claim_company_has_no_risks():
    guide=beginner_guide([],[],False,stop_reason='no_new_evidence')
    assert 'filters' in guide.overview
    assert 'does not establish' in guide.status
    assert 'narrower' not in guide.status


def test_model_failure_is_visible_without_opening_technical_details():
    guide=beginner_guide([],[],False,stop_reason='assessment_error',has_observations=True)
    assert 'local AI' in guide.overview
    assert 'research-system failure' in guide.status
