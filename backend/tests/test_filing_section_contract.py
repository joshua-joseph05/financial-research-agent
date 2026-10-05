import pytest
from pydantic import ValidationError
from app.tools.registry import FilingArgs,ToolRegistry
from app.evaluation.sources import BenchmarkRegistry
from app.schemas import ToolCall


def test_model_schema_only_offers_sections_the_provider_accepts():
    spec=next(s for s in ToolRegistry().descriptions() if s['name']=='get_sec_filings')
    options=spec['input_schema']['properties']['section']['anyOf']
    assert next(o['enum'] for o in options if 'enum' in o)==['business','risks','md&a']


@pytest.mark.parametrize('section',['risk','risk factors','invented-section'])
def test_bad_section_is_invalid_input_not_missing_evidence(section):
    with pytest.raises(ValidationError):FilingArgs(ticker='NVDA',section=section)
    call=ToolCall(name='get_sec_filings',arguments={'ticker':'NVDA','section':section})
    assert ToolRegistry().execute(call,{}).status=='error'
    assert BenchmarkRegistry().execute(call,{}).status=='error'


@pytest.mark.parametrize('section',['business','risks','md&a',None])
def test_supported_section_keeps_frozen_evidence_available(section):
    call=ToolCall(name='get_sec_filings',arguments={'ticker':'NVDA','section':section})
    result=BenchmarkRegistry().execute(call,{})
    assert result.status=='ok' and result.evidence
    if section:assert all(e.section==section for e in result.evidence)


def test_normalized_uppercase_section_still_works():
    registry=ToolRegistry()
    call=registry.normalize_call(ToolCall(name='get_sec_filings',arguments={'ticker':'NVDA','section':' RISKS '}))
    assert registry.execute(call,{}).status=='ok'
