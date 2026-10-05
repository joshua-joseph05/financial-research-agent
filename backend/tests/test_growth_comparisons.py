from copy import deepcopy
import pytest
from app.agent.comparisons import growth_comparison_findings
from app.agent.graph import structural_check
from app.evaluation.sources import BenchmarkRegistry
from app.schemas import ToolCall


def sample(tickers=('NVDA','AMD')):
    registry=BenchmarkRegistry();obs={};sources={}
    for ticker in tickers:
        result=registry.execute(ToolCall(name='get_financial_metric_history',arguments={'ticker':ticker,'metric':'operating_cash_flow','years':2}),obs)
        obs.update({e.id:e.model_dump() for e in result.evidence});sources.update({s.id:s.model_dump() for s in result.sources})
        result=registry.execute(ToolCall(name='calculate_financial_metrics',arguments={'operation':'growth','evidence_ids':[f'fixture:{ticker}:operating_cash_flow:2025',f'fixture:{ticker}:operating_cash_flow:2024']}),obs)
        obs.update({e.id:e.model_dump() for e in result.evidence});sources.update({s.id:s.model_dump() for s in result.sources})
    return obs,sources


def test_comparison_answers_faster_question_and_retains_both_provenance_chains():
    obs,sources=sample();findings=growth_comparison_findings(obs)
    assert len(findings)==1
    assert 'NVDA operating cash flow grew faster in percentage terms than AMD' in findings[0]['text']
    assert len(findings[0]['evidence_ids'])==2
    assert structural_check(findings[0],{'observations':obs,'sources':sources},strict_claims=True,issuer_names={'NVDA':'NVIDIA','AMD':'AMD'}) is None


@pytest.mark.parametrize('failure',['currency','metric','dates','scope','segment','value','missing','duplicate','single'])
def test_incompatible_or_unreproduced_changes_never_get_a_ranking(failure):
    obs,sources=sample();target=next(e for e in obs.values() if e.get('operation') and e['ticker']=='AMD')
    raw=[obs[k] for k in target['input_ids']]
    if failure=='currency':
        for e in raw:e['unit']='EUR'
    elif failure=='metric':
        for e in raw:e['metric']='revenue'
    elif failure=='dates':
        for e in raw:e['period_start']=e['period_start'][:4]+'-01-02'
    elif failure=='scope':
        for e in raw:e['scope']='segment'
    elif failure=='segment':
        for e in raw:e['segment']='Devices'
    elif failure=='value':target['value']='999'
    elif failure=='missing':del obs[target['input_ids'][0]]
    elif failure=='duplicate':obs['duplicate']={**target,'id':'duplicate'}
    elif failure=='single':del obs[target['id']]
    assert growth_comparison_findings(obs)==[]


def test_opposite_directions_are_explicit_not_called_faster_growth():
    obs,sources=sample(('MSFT','AAPL'));finding=growth_comparison_findings(obs)[0]
    assert 'AAPL increased, while MSFT decreased.' in finding['text']
    assert 'grew faster' not in finding['text']
