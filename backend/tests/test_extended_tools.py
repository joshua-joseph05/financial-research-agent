import json
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from email.utils import format_datetime
import httpx
import pytest
from bs4 import BeautifulSoup
from app.providers.sec import annual_facts
from app.providers import research_sources as sources
from app.schemas import Evidence, ToolCall
from app.tools.registry import ToolRegistry
from app.tools.extended import EXTRA_SPECS
from app.agent.graph import structural_check


def data(years=5):
    def rows(factor):
        return [dict(start=f'{year}-01-01', end=f'{year}-12-31', val=factor * (year-2018), form='10-K', filed=f'{year+1}-02-01', accn=f'0000000001-{str(year+1)[2:]}-000001') for year in range(2020, 2020+years)]
    return {'facts': {'us-gaap': {tag: {'units': {'USD': rows(factor)}} for tag, factor in [('Revenues',100),('OperatingIncomeLoss',20),('NetIncomeLoss',15),('NetCashProvidedByUsedInOperatingActivities',30),('PaymentsToAcquirePropertyPlantAndEquipment',10)]}}}


class FakeSEC:
    def __init__(self):
        self.urls=[]
        self.html=''
    def resolve(self,ticker):
        return ticker.upper(), '0000000001', ticker.upper()+' INC'
    def get(self,url,json=True):
        self.urls.append(url)
        if 'companyfacts' in url:
            return data()
        if 'submissions' in url:
            return {'filings': {'recent': {'form':['8-K','10-K'], 'items':['2.02',''], 'accessionNumber':['0000000001-25-000002','0000000001-25-000001'], 'primaryDocument':['results.htm','annual.htm'],'filingDate':['2025-02-02','2025-02-01']}}}
        return self.html
    def execute(self,name,args):
        return annual_facts(data(),args.ticker,'0000000001')


def call(name,args,sec=None,observations=None):
    return ToolRegistry(sec=sec or FakeSEC()).execute(ToolCall(name=name,arguments=args),observations or {})


def test_new_tools_live_only_and_calculation_schema_targets_correct_tool():
    assert not set(EXTRA_SPECS) & {d['name'] for d in ToolRegistry().descriptions()}
    registry=ToolRegistry(sec=FakeSEC())
    assert len(registry.descriptions())==12
    records=annual_facts(data(),'MSFT','0000000001').evidence
    specs={d['name']:d for d in registry.descriptions({e.id:e.model_dump() for e in records})}
    assert 'anyOf' in specs['calculate_financial_metrics']['input_schema']
    assert 'evidence_id' in specs['reconcile_financial_figures']['input_schema']['properties']


@pytest.mark.parametrize('metric',['revenue','operating_income','net_income','operating_cash_flow','capital_expenditure'])
def test_history_returns_five_actual_annual_periods(metric):
    result=call('get_financial_metric_history',{'ticker':'MSFT','metric':metric,'years':5})
    assert result.status=='ok' and len(result.evidence)==5
    assert all(e.metric==metric and e.unit=='USD' and e.period_type=='annual' for e in result.evidence)
    assert len({e.period_end for e in result.evidence})==5


def test_history_limit_and_missing_years():
    assert call('get_financial_metric_history',{'ticker':'MSFT','years':11}).status=='error'
    result=call('get_financial_metric_history',{'ticker':'MSFT','years':10})
    assert len(result.evidence)==5
    assert any('Only 5 of 10' in text for text in result.limitations)


def test_comparison_preserves_both_issuers_and_reproducible_inputs():
    # Distinct issuers must have distinct fact provenance.
    sec=FakeSEC()
    sec.execute=lambda name,args: annual_facts(data(),args.ticker,'0000000001' if args.ticker=='MSFT' else '0000000002')
    result=call('compare_companies',{'tickers':['MSFT','AMD']},sec)
    assert result.status=='ok'
    margins=[e for e in result.evidence if e.operation=='operating_margin']
    assert len(margins)==4 and all(e.value=='20.0000' for e in margins)
    ids={e.id for e in result.evidence}
    assert all(set(e.input_ids)<=ids for e in margins)
    assert call('compare_companies',{'tickers':['MSFT','MSFT']}).status=='error'


def inline(value='600',scale='0',context='annual',dimension='',format='ixt:num-dot-decimal'):
    return f'''<html><xbrli:context id="annual"><xbrli:entity>{dimension}</xbrli:entity><xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period></xbrli:context><xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit><table><tr><td><ix:nonFraction name="us-gaap:Revenues" contextRef="{context}" unitRef="usd" format="{format}" scale="{scale}">{value}</ix:nonFraction></td></tr></table></html>'''


def revenue():
    return annual_facts(data(),'MSFT','0000000001').evidence[-2]


@pytest.mark.parametrize('html,status',[(inline(),'matched'),(inline('6',scale='2'),'matched'),(inline('601'),'mismatch'),(inline(context='wrong'),'unresolved'),(inline(dimension='<xbrli:segment>segment</xbrli:segment>'),'unresolved'),(inline(format='ixt:unsupported'),'unresolved')])
def test_reconcile_exact_context_units_and_scale(html,status):
    sec=FakeSEC();sec.html=html;record=revenue()
    result=call('reconcile_financial_figures',{'evidence_id':record.id},sec,{record.id:record.model_dump()})
    assert result.status=='ok'
    assert result.evidence[0].reconciliation_status==status


def test_reconciliation_mismatch_blocks_original_claim():
    sec=FakeSEC();sec.html=inline('601');record=revenue()
    result=call('reconcile_financial_figures',{'evidence_id':record.id},sec,{record.id:record.model_dump()})
    mismatch=result.evidence[0]
    state={'observations':{record.id:record.model_dump(),mismatch.id:mismatch.model_dump()},'sources':{record.source_id:{},mismatch.source_id:{}}}
    assert 'mismatch' in structural_check({'text':'Revenue was 600 USD.','evidence_ids':[record.id]},state)


def test_earnings_follows_only_same_filing_exhibits():
    sec=FakeSEC()
    sec.html='<p>'+('Quarterly revenue and earnings increased this quarter. '*3)+'</p><a href="release99.htm">Exhibit 99</a><a href="https://evil.invalid/ex99.htm">99</a>'
    result=call('get_earnings_information',{'ticker':'MSFT','limit':1},sec)
    assert result.status=='ok' and result.evidence
    assert any('release99.htm' in url for url in sec.urls)
    assert not any('evil' in url for url in sec.urls)
    assert all(e.scope=='unknown' for e in result.evidence)


def test_news_filters_dates_deduplicates_and_labels(monkeypatch):
    now=format_datetime(datetime.now(timezone.utc)-timedelta(days=1))
    xml=f'<rss><channel><item><title>Company reports results</title><link>https://news.google.com/example</link><pubDate>{now}</pubDate><source>Publisher</source></item><item><title>Old</title><link>https://example.com/old</link><pubDate>Mon, 01 Jan 2001 00:00:00 GMT</pubDate></item></channel></rss>'
    monkeypatch.setattr(sources,'public_get',lambda url:xml.encode())
    result=call('get_news',{'ticker':'MSFT'})
    assert len(result.evidence)==1 and 'UNVERIFIED NEWS HEADLINE' in result.evidence[0].text
    e=result.evidence[0]
    state={'observations':{e.id:e.model_dump()},'sources':{e.source_id:{}}}
    assert 'headlines' in structural_check({'text':'Company reports results.','evidence_ids':[e.id]},state)


def chart():
    stamp=int((datetime.now(timezone.utc)-timedelta(days=2)).timestamp())
    return {'chart':{'result':[{'meta':{'symbol':'MSFT','instrumentType':'EQUITY','currency':'USD','exchangeTimezoneName':'America/New_York'},'timestamp':[stamp],'indicators':{'quote':[{'close':[123.45]}]}}]}}


def test_market_has_timestamp_currency_and_no_financial_period(monkeypatch):
    monkeypatch.setattr(sources,'public_get',lambda url:json.dumps(chart()).encode())
    result=call('get_market_data',{'ticker':'MSFT'})
    e=result.evidence[0]
    assert e.value=='123.45' and e.unit=='USD' and e.period_end is None
    assert 'Not a current executable quote' in e.text


def test_market_rejects_wrong_symbol_and_no_fallback_on_rate_limit(monkeypatch):
    payload=chart();payload['chart']['result'][0]['meta']['symbol']='OTHER'
    monkeypatch.setattr(sources,'public_get',lambda url:json.dumps(payload).encode())
    assert call('get_market_data',{'ticker':'MSFT'}).status=='error'
    def unavailable(url):
        raise httpx.HTTPStatusError('rate limited',request=httpx.Request('GET',url),response=httpx.Response(429))
    monkeypatch.setattr(sources,'public_get',unavailable)
    result=call('get_market_data',{'ticker':'MSFT'})
    assert result.status=='error' and not result.evidence


def test_margin_history_calculates_each_year_with_original_inputs():
    result=call('get_financial_metric_history',{'ticker':'MSFT','metric':'operating_margin','years':5})
    margins=[e for e in result.evidence if e.operation=='operating_margin']
    assert len(margins)==5 and all(e.value=='20.0000' for e in margins)
    assert len(result.evidence)==15
    assert len({e.id for e in result.evidence})==15


def test_comparison_warns_about_different_windows():
    sec=FakeSEC()
    def execute(name,args):
        payload=data()
        if args.ticker=='AMD':
            for concept in payload['facts']['us-gaap'].values():
                for row in concept['units']['USD']:
                    row['end']=row['end'][:4]+'-12-30'
        return annual_facts(payload,args.ticker,'0000000001' if args.ticker=='MSFT' else '0000000002')
    sec.execute=execute
    result=call('compare_companies',{'tickers':['MSFT','AMD']},sec)
    assert any('Fiscal windows differ' in text for text in result.limitations)


def test_market_skips_current_session_partial_bar(monkeypatch):
    payload=chart()
    result=payload['chart']['result'][0]
    result['timestamp'].append(int(datetime.now(timezone.utc).timestamp()))
    result['indicators']['quote'][0]['close'].append(999)
    monkeypatch.setattr(sources,'public_get',lambda url:json.dumps(payload).encode())
    assert call('get_market_data',{'ticker':'MSFT'}).evidence[0].value=='123.45'


def test_bad_rss_is_tool_error(monkeypatch):
    monkeypatch.setattr(sources,'public_get',lambda url:b'not xml')
    assert call('get_news',{'ticker':'MSFT'}).status=='error'


def test_news_requirement_runs_through_graph_without_forcing_financials(monkeypatch):
    from app.agent.graph import run_research
    from app.schemas import Plan, Decision, EvidenceReview, Finding, Verification, ClaimCheck, Synthesis
    now=format_datetime(datetime.now(timezone.utc)-timedelta(days=1))
    monkeypatch.setattr(sources,'public_get',lambda url:f'<rss><channel><item><title>MSFT announces results</title><link>https://news.google.com/article</link><pubDate>{now}</pubDate></item></channel></rss>'.encode())
    class Model:
        def respond(self,phase,context,schema,timeout):
            if phase=='plan':
                assert any(t['name']=='get_news' for t in context['available_tools'])
                return Plan(companies=['MSFT'],questions=['Find news headlines'],evidence_requirements=['news_headlines'])
            if phase=='investigate':
                return Decision(action='tool',reason='Retrieve dated headlines',tool=ToolCall(name='get_news',arguments={'ticker':'MSFT'}))
            if phase=='assess':
                key=next(iter(context['observations']))
                return EvidenceReview(findings=[Finding(id='claim_news',text='An unverified headline reports that MSFT announces results.',evidence_ids=[key])],open_questions=[],sufficient=True)
            if phase=='verify':
                return Verification(coverage='sufficient',checks=[ClaimCheck(finding_id='claim_news',status='supported',explanation='Only describes the headline, not the underlying event.')])
            return Synthesis(answer='',finding_ids=['claim_news'],limitations=[],follow_up_questions=[])
    result=run_research('Find recent MSFT news headlines',Model(),registry=ToolRegistry(sec=FakeSEC()))
    assert result['report']['complete']
    assert [c['name'] for c in result['tool_calls']]==['get_news']


def test_reconciliation_does_not_certify_hidden_table_fact():
    html=inline().replace('<table>','<table style="display: none">')
    outcome,_=sources.reconcile_inline(BeautifulSoup(html,'html.parser'),revenue())
    assert outcome=='unresolved'


def test_nonfinite_financial_history_is_not_returned():
    payload=data()
    for row in payload['facts']['us-gaap']['Revenues']['units']['USD']:
        row['val']='NaN'
    assert annual_facts(payload,'MSFT','0000000001',5,['revenue']).status=='no_data'
