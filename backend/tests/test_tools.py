import pytest

from app.schemas import Evidence, ToolCall
from app.tools.calculations import calculate
from app.tools.registry import ToolRegistry


def number(metric, value, period="2025", ticker="MSFT", unit="USD_millions"):
    return Evidence(id=f"{ticker}:{period}:{metric}", source_id="test", ticker=ticker,
        text="Test", metric=metric, value=value, unit=unit, period=period)


def test_margin_and_growth_use_decimal():
    assert calculate("operating_margin", [number("operating_income", "84"), number("revenue", "240")]) == ("35.0000", "percent")
    assert calculate("growth", [number("revenue", "240"), number("revenue", "200", "2024")]) == ("20.0000", "percent")


@pytest.mark.parametrize("inputs", [
    [number("operating_income", "84", "2024"), number("revenue", "240")],
    [number("operating_income", "84", ticker="NVDA"), number("revenue", "240")],
    [number("operating_income", "84", unit="EUR"), number("revenue", "240")],
    [number("operating_income", "84"), number("revenue", "0")],
    [number("operating_income", "NaN"), number("revenue", "240")],
])
def test_incompatible_or_invalid_calculation_inputs_are_rejected(inputs):
    with pytest.raises(ValueError):
        calculate("operating_margin", inputs)


def test_missing_and_invalid_tool_inputs_are_distinct():
    registry = ToolRegistry()
    missing = registry.execute(ToolCall(name="get_financials", arguments={"ticker": "UNKNOWN"}), {})
    invalid = registry.execute(ToolCall(name="get_financials", arguments={"ticker": "NVDA", "extra": 1}), {})
    assert missing.status == "no_data"
    assert invalid.status == "error"


def test_cannot_calculate_from_fabricated_evidence_ids():
    result = ToolRegistry().execute(ToolCall(name="calculate_financial_metrics", arguments={
        "operation": "growth", "evidence_ids": ["fake1", "fake2"]}), {})
    assert result.status == "error"


def test_calculation_choices_require_compatible_observed_inputs():
    registry=ToolRegistry()
    assert all(t['name'] != 'calculate_financial_metrics' for t in registry.descriptions({}, []))
    data=registry.execute(ToolCall(name='get_financials',arguments={'ticker':'MSFT'}),{})
    observed={e.id:e.model_dump() for e in data.evidence}
    spec=next(t for t in registry.descriptions(observed,[]) if t['name']=='calculate_financial_metrics')
    options=spec['input_schema']['anyOf']
    assert options
    for choice in options:
        operation=choice['properties']['operation']['const']
        keys=[item['const'] for item in choice['properties']['evidence_ids']['prefixItems']]
        assert operation != 'margin_change'  # No calculated margins exist yet.
        result = registry.execute(ToolCall(name='calculate_financial_metrics', arguments={'operation': operation, 'evidence_ids': keys}), observed)
        assert result.status == 'ok'
        local = {**observed, **{e.id: e.model_dump() for e in result.evidence}}
        for record in result.evidence:
            assert calculate(record.operation, [Evidence.model_validate(local[key]) for key in record.input_ids]) == (record.value, record.unit)


def test_completed_calculation_is_removed_from_choices():
    registry=ToolRegistry()
    data=registry.execute(ToolCall(name='get_financials',arguments={'ticker':'MSFT'}),{})
    observed={e.id:e.model_dump() for e in data.evidence}
    args={'operation':'operating_margin','evidence_ids':['MSFT:2024:operating_income','MSFT:2024:revenue']}
    result=registry.execute(ToolCall(name='calculate_financial_metrics',arguments=args),observed)
    observed.update({e.id:e.model_dump() for e in result.evidence})
    history=[{'name':'calculate_financial_metrics','arguments':args,'result':result.model_dump()}]
    spec=next(t for t in registry.descriptions(observed,history) if t['name']=='calculate_financial_metrics')
    for choice in spec['input_schema']['anyOf']:
        candidate={'operation':choice['properties']['operation']['const'],
                   'evidence_ids':[x['const'] for x in choice['properties']['evidence_ids']['prefixItems']]}
        assert candidate != args


def test_batch_margin_comparison_returns_reproducible_results():
    registry = ToolRegistry()
    data = registry.execute(ToolCall(name='get_financials', arguments={'ticker':'MSFT'}), {})
    observed = {e.id:e.model_dump() for e in data.evidence}
    call = ToolCall(name='calculate_financial_metrics', arguments={'operation':'compare_operating_margins', 'evidence_ids':[
        'MSFT:2025:operating_income','MSFT:2025:revenue','MSFT:2024:operating_income','MSFT:2024:revenue']})
    result = registry.execute(call, observed)
    assert result.status == 'ok'
    assert [e.value for e in result.evidence] == ['35.0000','30.0000','5.0000']
    assert result.evidence[-1].input_ids == [e.id for e in result.evidence[:2]]
    assert len(observed) == 4  # Tool execution does not mutate caller state.
    call.arguments['evidence_ids'].reverse()
    assert registry.execute(call, observed).status == 'error'
