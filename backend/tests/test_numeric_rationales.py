from copy import deepcopy
import pytest
from app.evaluation.sources import BenchmarkRegistry
from app.schemas import ToolCall
from app.ideas.models import Rationale
from app.ideas.numeric_rationales import grounded_numeric_rationale


def sample():
    registry=BenchmarkRegistry()
    data=registry.execute(ToolCall(name='get_financials',arguments={'ticker':'NVDA'}),{})
    obs={e.id:e.model_dump() for e in data.evidence};sources={s.id:s.model_dump() for s in data.sources}
    result=registry.execute(ToolCall(name='calculate_financial_metrics',arguments={'operation':'growth','evidence_ids':['fixture:NVDA:revenue:2025','fixture:NVDA:revenue:2024']}),obs)
    obs.update({e.id:e.model_dump() for e in result.evidence});sources.update({s.id:s.model_dump() for s in result.sources})
    return obs,sources,result.evidence[0].id


@pytest.mark.parametrize('text',['Revenue growth proves strong demand.','Revenue is projected to increase.','The stock is cheap because revenue grew.'])
def test_numeric_records_cannot_acquire_causal_forecast_or_valuation_claims(text):
    obs,sources,key=sample()
    result=grounded_numeric_rationale(Rationale(text=text,evidence_ids=[key]),obs,sources)
    assert 'NVDA revenue changed by 50.0000% from 2024-12-31 to 2025-12-31.' in result.text
    assert 'Calculation (USD inputs): (150 − 100) ÷ 100 = 50.0000%.' in result.text
    assert result.text.endswith('This is an increase.')
    assert not any(word in result.text.lower() for word in ('demand','projected','cheap'))
    assert result.evidence_ids==[key]


def test_altered_calculation_is_not_rendered_as_verified():
    obs,sources,key=sample();obs=deepcopy(obs);obs[key]['value']='999'
    with pytest.raises(ValueError,match='reproduction'):
        grounded_numeric_rationale(Rationale(text='Growth improved.',evidence_ids=[key]),obs,sources)


def test_interpretation_with_a_passage_keeps_its_model_review():
    claim=Rationale(text='Management attributes growth to demand.',evidence_ids=['passage:x'])
    result=grounded_numeric_rationale(claim,{'passage:x':{'id':'passage:x','text':'Demand increased.','value':None}}, {})
    assert result==claim


def test_only_reproduced_exact_numeric_statement_gets_python_approval():
    from app.ideas.claim_review import python_verified_claim_ids, review_items, reviewed_tickers, ClaimReview
    obs,sources,key=sample()
    claim=grounded_numeric_rationale(Rationale(text='Growth.',evidence_ids=[key]),obs,sources)
    ideas=[{'ticker':'NVDA','reasons':[claim.model_dump()],'risks':[]}]
    ids=python_verified_claim_ids(ideas,obs,sources)
    assert ids=={'NVDA:reasons:0'}
    result=reviewed_tickers(ideas,review_items(ideas,obs),ClaimReview(checks=[],actions=[]),python_verified_ids=ids)
    assert result['approved_claim_ids']==['NVDA:reasons:0']
    assert not result['checks'][0]['supported']
    ideas[0]['reasons'][0]['text']+=' This proves demand is strong.'
    assert not python_verified_claim_ids(ideas,obs,sources)


@pytest.mark.parametrize('failure',['value','missing_input','cycle','source','issuer','passage'])
def test_invalid_evidence_cannot_get_python_approval(failure):
    from app.ideas.claim_review import python_verified_claim_ids
    obs,sources,key=sample()
    claim=grounded_numeric_rationale(Rationale(text='Growth.',evidence_ids=[key]),obs,sources)
    if failure=='value':obs[key]['value']='999'
    elif failure=='missing_input':del obs[obs[key]['input_ids'][0]]
    elif failure=='cycle':obs[key]['input_ids']=[key]
    elif failure=='source':sources.clear()
    elif failure=='issuer':obs[obs[key]['input_ids'][0]]['ticker']='AMD'
    elif failure=='passage':obs[key]['value']=None
    assert not python_verified_claim_ids([{'ticker':'NVDA','reasons':[claim.model_dump()],'risks':[]}],obs,sources)


@pytest.mark.parametrize('ticker,word',[('MSFT','decrease'),('AAPL','increase')])
def test_cash_flow_direction_is_derived_from_verified_arithmetic(ticker,word):
    registry=BenchmarkRegistry()
    result=registry.execute(ToolCall(name='get_financial_metric_history',arguments={'ticker':ticker,'metric':'operating_cash_flow','years':2}),{})
    obs={e.id:e.model_dump() for e in result.evidence};sources={s.id:s.model_dump() for s in result.sources}
    result=registry.execute(ToolCall(name='calculate_financial_metrics',arguments={'operation':'growth','evidence_ids':[f'fixture:{ticker}:operating_cash_flow:2025',f'fixture:{ticker}:operating_cash_flow:2024']}),obs)
    obs.update({e.id:e.model_dump() for e in result.evidence});sources.update({s.id:s.model_dump() for s in result.sources})
    output=grounded_numeric_rationale(Rationale(text='Change',evidence_ids=[result.evidence[0].id]),obs,sources)
    assert output.text.endswith(f'This is a{ "n" if word=="increase" else ""} {word}.')
    assert result.evidence[0].value in output.text


def test_zero_change_is_not_labelled_as_an_increase():
    from app.agent.attribution import calculation_findings
    obs={'a':{'metric':'revenue','period':'2025-12-31'},'b':{'metric':'revenue','period':'2024-12-31'},'c':{'id':'c','ticker':'X','operation':'growth','input_ids':['a','b'],'value':'0.0000'}}
    assert calculation_findings(obs)[0]['text'].endswith('There is no change at the displayed precision.')
    obs['c']['value']='NaN'
    assert calculation_findings(obs)==[]
