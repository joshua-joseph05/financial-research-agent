from types import SimpleNamespace
import pytest
from app.ideas.identity import verify_references
from app.ideas.models import IdeasClarification
from app.providers.sec import SECClient

ROWS={str(i):r for i,r in enumerate([
    {'ticker':'AAPL','title':'Apple Inc.','cik_str':1},
    {'ticker':'APLE','title':'Apple Hospitality REIT, Inc.','cik_str':2},
    {'ticker':'MCY','title':'Mercury General Corp','cik_str':3},
    {'ticker':'MRCY','title':'Mercury Systems Inc','cik_str':4},
    {'ticker':'TEST.A','title':'Test Holdings Inc','cik_str':5},
    {'ticker':'TEST.B','title':'Test Holdings Inc','cik_str':5}])}

@pytest.fixture
def sec():
    client=SECClient('Research tests contact@example.com')
    client.get=lambda *args,**kwargs:ROWS
    yield client
    client.close()


def test_unique_brand_name_resolves_but_shared_prefix_does_not(sec):
    assert sec.resolve('Apple')[0]=='AAPL'
    assert sec.resolve('Apple Hospitality')[0]=='APLE'
    assert sec.resolve('MRCY')[0]=='MRCY'
    with pytest.raises(ValueError,match='uniquely'):sec.resolve('Mercury')
    assert sec.resolve('Test Holdings')[1]=='0000000005'


def test_original_reference_must_match_selected_issuer(sec):
    registry=SimpleNamespace(sec=sec)
    verify_references(SimpleNamespace(company_references=['Apple'],tickers=['AAPL']),'Tell me about Apple',registry)
    with pytest.raises(IdeasClarification):verify_references(SimpleNamespace(company_references=['Apple'],tickers=['APLE']),'Tell me about Apple',registry)
    with pytest.raises(IdeasClarification):verify_references(SimpleNamespace(company_references=['Mercury'],tickers=['MRCY']),'Should I buy Mercury?',registry)
    with pytest.raises(IdeasClarification):verify_references(SimpleNamespace(company_references=['Apple'],tickers=['AAPL']),'Tell me about Microsoft',registry)


def test_ticker_must_not_be_extracted_from_inside_an_unrelated_word(sec):
    with pytest.raises(IdeasClarification,match='matched'):
        verify_references(SimpleNamespace(company_references=['AI'],tickers=['AI']),'Explain investing',SimpleNamespace(sec=sec))


def test_ambiguous_company_stops_before_financial_research():
    from app.evaluation.recording import run_case
    from app.evaluation.benchmark_data import load_cases
    class Model:
        def respond(self,phase,context,schema,timeout):
            if phase=='assistant_route':return schema(workflow='investment',reason='Investment question')
            assert phase=='ideas_select'
            return schema(kind='named_companies',tickers=['MRCY'],company_references=['Mercury'])
    case=next(c for c in load_cases() if c.id=='insufficient_evidence-01')
    result=run_case(case,Model(),execution_profile='efficient')
    assert result['status']=='clarification'
    assert result['telemetry']['model_calls']==2
    assert not result['trace']['tool_calls']


def test_exact_ticker_takes_precedence_over_another_issuer_name(sec):
    rows={**ROWS,'collision':{'ticker':'OTHER','title':'AAPL','cik_str':99}}
    sec.get=lambda *args,**kwargs:rows
    assert sec.resolve('AAPL')[1]=='0000000001'
