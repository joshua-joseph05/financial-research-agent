import pytest
from app.evaluation.sources import BenchmarkRegistry
from app.schemas import ToolCall
from app.tools.comparison_enrichment import add_revenue_growth


def comparison():
    registry = BenchmarkRegistry()
    result = registry.execute(ToolCall(name='compare_companies', arguments={'tickers':['NVDA','AMD']}), {})
    return registry, result


def test_comparison_growth_preserves_inputs_and_does_not_refetch():
    registry, original = comparison()
    before = original.model_dump()
    registry.calls.clear()
    result = add_revenue_growth(registry, original)
    assert original.model_dump() == before
    growth = {e.ticker:e for e in result.evidence if e.operation == 'growth'}
    assert {t:e.value for t,e in growth.items()} == {'NVDA':'50.0000','AMD':'20.0000'}
    assert all(e.input_ids == [f'fixture:{t}:revenue:2025', f'fixture:{t}:revenue:2024'] for t,e in growth.items())
    assert all(c['name'] == 'calculate_financial_metrics' for c in registry.calls)
    assert add_revenue_growth(registry, result).model_dump() == result.model_dump()


@pytest.mark.parametrize('problem', ['duplicate','scope','unit','quarter','zero','missing'])
def test_ambiguous_or_incompatible_growth_is_withheld(problem):
    registry, result = comparison()
    row = next(e for e in result.evidence if e.id=='fixture:NVDA:revenue:2024')
    if problem == 'duplicate': result.evidence.append(row.model_copy(update={'id':'duplicate'}))
    elif problem == 'scope': row.scope = 'segment'
    elif problem == 'unit': row.unit = 'EUR'
    elif problem == 'quarter': row.period_type = 'quarterly'
    elif problem == 'zero': row.value = '0'
    else: result.evidence.remove(row)
    enriched = add_revenue_growth(registry, result)
    assert not any(e.operation=='growth' and e.ticker=='NVDA' for e in enriched.evidence)
    assert any(e.operation=='growth' and e.ticker=='AMD' for e in enriched.evidence)


@pytest.mark.parametrize('problem',['unknown_period','both_segments'])
def test_growth_does_not_infer_annual_or_company_scope(problem):
    registry,result=comparison()
    for row in result.evidence:
        if row.ticker=='NVDA' and row.metric=='revenue':
            if problem=='unknown_period':row.period_type=None
            else:row.scope='segment';row.segment='Example segment'
    enriched=add_revenue_growth(registry,result)
    assert not any(e.operation=='growth' and e.ticker=='NVDA' for e in enriched.evidence)
