import httpx
import pytest

from app.providers.sec import SECClient, annual_facts
from app.providers.filing_context import ContextualFiling
from app.schemas import Evidence, ToolCall
from app.tools.registry import ToolRegistry
from app.tools.calculations import calculate


def fact(start='2023-07-01', end='2024-06-30', val=100, filed='2024-07-30', accn='0000000001-24-000001', form='10-K'):
    return dict(start=start, end=end, val=val, filed=filed, accn=accn, form=form)


def payload(revenue, income):
    return {'facts': {'us-gaap': {
        'RevenueFromContractWithCustomerExcludingAssessedTax': {'units': {'USD': revenue}},
        'OperatingIncomeLoss': {'units': {'USD': income}}}}}


def test_annual_excludes_quarter_and_ytd_and_uses_latest_restatement():
    result = annual_facts(payload([
        fact(), fact(val=120, filed='2025-07-30', accn='0000000001-25-000001'),
        fact(start='2024-04-01', val=30), fact(start='2024-01-01', val=60),
    ], [fact(val=36)]), 'TEST', '0000000001')
    assert len(result.evidence) == 2
    revenue, income = result.evidence
    assert revenue.value == '120'
    assert revenue.period_start == '2023-07-01'
    assert revenue.period == '2024-06-30'
    assert revenue.source_id.endswith('0000000001-25-000001')
    assert all(not s.synthetic for s in result.sources)
    assert calculate('operating_margin', [income, revenue]) == ('30.0000', 'percent')


def test_mismatched_windows_not_paired():
    assert annual_facts(payload([fact()], [fact(start='2023-06-25')]), 'TEST', '1').status == 'no_data'


def test_other_currencies_not_silently_treated_as_usd():
    data = payload([fact()], [fact()])
    data['facts']['us-gaap']['OperatingIncomeLoss']['units'] = {'EUR': [fact()]}
    assert annual_facts(data, 'TEST', '1').status == 'no_data'


def test_amendments_and_duplicate_comparatives():
    amended = fact(val=90, filed='2024-08-20', form='10-K/A')
    result = annual_facts(payload([fact(), amended, amended], [fact(val=18)]), 'TEST', '1')
    assert len(result.evidence) == 2
    assert result.evidence[0].value == '90'


@pytest.mark.parametrize('kind', ['quarterly', 'ytd'])
def test_calculations_reject_nonannual(kind):
    a = Evidence(id='a', source_id='s', ticker='T', text='test fact', metric='operating_income', value='10', unit='USD', period='2024', period_type=kind)
    b = a.model_copy(update={'id': 'b', 'metric': 'revenue', 'value': '100'})
    with pytest.raises(ValueError, match='annual'):
        calculate('operating_margin', [a, b])


def test_calculations_reject_same_label_different_dates():
    a = Evidence(id='a', source_id='s', ticker='T', text='test fact', metric='operating_income', value='10', unit='USD', period='2024', period_type='annual', period_start='2023-07-01', period_end='2024-06-30')
    b = a.model_copy(update={'id': 'b', 'metric': 'revenue', 'period_start': '2023-06-25'})
    with pytest.raises(ValueError, match='identical'):
        calculate('operating_margin', [a, b])


def test_client_identification_cache_and_no_fixture_fallback():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(403, text='Denied')
    client = SECClient('Unit tests tests@example.invalid', transport=httpx.MockTransport(handler))
    try:
        registry = ToolRegistry(sec=client)
        result = registry.execute(ToolCall(name='get_financials', arguments={'ticker': 'MSFT'}), {})
        assert result.status == 'error'
        assert result.evidence == []
        assert not registry.synthetic
        assert requests[0].headers['user-agent'] == 'Unit tests tests@example.invalid'
    finally:
        client.close()


def test_http_cache_and_issuer_resolution():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'0': {'ticker': 'TEST', 'title': 'TEST CORP', 'cik_str': 1}})
    client = SECClient('Unit tests tests@example.invalid', transport=httpx.MockTransport(handler))
    try:
        assert client.resolve('TEST') == ('TEST', '0000000001', 'TEST CORP')
        assert client.resolve('TEST CORP')[0] == 'TEST'
        assert len(calls) == 1
        with pytest.raises(ValueError, match='uniquely'):
            client.resolve('UNKNOWN')
    finally:
        client.close()


def test_filing_parser_excludes_scripts_and_xbrl_header():
    parser = ContextualFiling()
    parser.feed('<script>' + 'bad ' * 40 + '</script><ix:header>' + 'hidden ' * 40 + '</ix:header><p>' + 'Operating margin explanation. ' * 8 + '</p>')
    assert len(parser.passages()) == 1
    assert 'hidden' not in parser.passages()[0].text
    assert 'bad' not in parser.passages()[0].text


def test_live_calculation_source_and_dates():
    class FakeSEC:
        pass
    registry = ToolRegistry(sec=FakeSEC())
    raw = annual_facts(payload([fact()], [fact(val=30)]), 'TEST', '1')
    revenue, income = raw.evidence
    result = registry.execute(ToolCall(name='calculate_financial_metrics', arguments={
        'operation': 'operating_margin', 'evidence_ids': [income.id, revenue.id]}),
        {e.id: e.model_dump() for e in raw.evidence})
    assert result.status == 'ok'
    assert not result.sources[0].synthetic
    assert 'Synthetic' not in result.evidence[0].text
    assert result.evidence[0].period_start == revenue.period_start


def test_sec_tool_to_report_preserves_live_labels_and_sources():
    from app.agent.graph import run_research
    from app.schemas import Plan, Decision, EvidenceReview, Finding, Verification, ClaimCheck, Synthesis

    class OfflineSEC:
        def execute(self, name, args):
            return annual_facts(payload([fact()], [fact(val=30)]), 'TEST', '1')

    class ControlledModel:
        def respond(self, phase, context, schema, timeout):
            assert context['data_mode'] == 'SEC filings'
            if phase == 'plan':
                return Plan(companies=['TEST'], questions=['What is annual operating income?'])
            if phase == 'investigate':
                return Decision(action='tool', reason='Retrieve reported values', tool=ToolCall(name='get_financials', arguments={'ticker': 'TEST'}))
            if phase == 'assess':
                row = next(e for e in context['observations'].values() if e['metric'] == 'operating_income')
                return EvidenceReview(findings=[Finding(id='income', text='Annual operating income was 30 USD.', evidence_ids=[row['id']])], open_questions=[], sufficient=True)
            if phase == 'verify':
                return Verification(coverage='sufficient', checks=[ClaimCheck(finding_id='income', status='supported', explanation='Matches cited fact')])
            return Synthesis(answer='Annual operating income was 30 USD.', finding_ids=['income'], limitations=[], follow_up_questions=[])

    state = run_research('What is annual operating income?', ControlledModel(), registry=ToolRegistry(sec=OfflineSEC()))
    report = state['report']
    assert report['complete']
    assert not report['synthetic']
    assert not report['sources'][0]['synthetic']
    assert report['sources'][0]['accession']
    assert not any('SYNTHETIC' in item for item in report['limitations'])
    assert report['answer'] == 'Annual operating income was 30 USD.'


def test_sec_filing_search_returns_real_url_and_bounded_passages(monkeypatch):
    monkeypatch.setattr('app.providers.sec.time.sleep', lambda _: None)
    def handler(request):
        path = request.url.path
        if path.endswith('company_tickers.json'):
            return httpx.Response(200, json={'0': {'ticker': 'TEST', 'title': 'TEST CORP', 'cik_str': 1}})
        if '/submissions/' in path:
            return httpx.Response(200, json={'name': 'TEST CORP', 'filings': {'recent': {
                'form': ['10-Q', '10-K'], 'accessionNumber': ['0000000001-25-000001', '0000000001-24-000001'],
                'primaryDocument': ['quarter.htm', 'annual.htm'], 'filingDate': ['2025-02-01', '2024-07-30']}}})
        assert path.endswith('/annual.htm')
        return httpx.Response(200, text='<p>' + 'Operating income increased due to lower expenses. ' * 4 + '</p>')
    client = SECClient('Unit tests tests@example.invalid', transport=httpx.MockTransport(handler))
    try:
        result = ToolRegistry(sec=client).execute(ToolCall(name='search_sec_filings', arguments={'ticker': 'TEST', 'query': 'operating income'}), {})
        assert result.status == 'ok'
        assert len(result.evidence) == 1
        assert result.sources[0].uri.endswith('/000000000124000001/annual.htm')
        assert result.sources[0].filed == '2024-07-30'
        assert not result.sources[0].synthetic
    finally:
        client.close()


def test_passage_ranking_favors_focused_financial_phrases():
    from app.providers.sec import rank_passages
    generic = 'Operating risks may affect margin, expenses and change factors. ' + 'General business uncertainty. ' * 100
    explanation = 'Operating margin increased because operating expenses grew more slowly than revenue.'
    assert rank_passages([generic, explanation], 'operating margin change operating expenses')[0][1] == explanation


def test_compact_fact_ids_still_distinguish_fiscal_windows():
    first = fact()
    second = fact(start='2024-07-01', end='2025-06-30', filed='2025-07-30')
    result = annual_facts(payload([first, second], [first, second]), 'TEST', '1')
    ids = [e.id for e in result.evidence]
    assert len(set(ids)) == 4
    assert all(len(key) < 25 for key in ids)
    assert all(e.source_id and e.period_start and e.period_end for e in result.evidence)


def test_change_query_prioritizes_reported_outcomes_over_possible_risks():
    from app.providers.sec import rank_passages
    risk = 'Operating margin may decrease because operating expenses could increase.'
    history = 'Operating income increased driven by revenue growth and lower expenses.'
    assert rank_passages([risk, history], 'operating margin change explanation')[0][1] == history


def test_annual_default_window_is_latest_two_shared_years():
    rows = [fact(start=f'{year-1}-07-01', end=f'{year}-06-30', filed='2025-07-30') for year in (2023, 2024, 2025)]
    result = annual_facts(payload(rows, rows), 'TEST', '1')
    assert {e.period for e in result.evidence} == {'2024-06-30', '2025-06-30'}


def test_live_filters_use_explicit_context_not_filing_date(monkeypatch):
    from app.tools.registry import SearchArgs
    monkeypatch.setattr('app.providers.sec.time.sleep', lambda _: None)
    html = '''<h1>Item 7</h1><h2>SUMMARY RESULTS OF OPERATIONS</h2>
    <h3>Fiscal Year 2025 Compared with Fiscal Year 2024</h3>
    <p>Operating income increased because revenue growth exceeded expense growth across the consolidated company.</p>
    <h2>SEGMENT RESULTS OF OPERATIONS</h2><h3>Fiscal Year 2025 Compared with Fiscal Year 2024</h3>
    <h3>Consumer Business</h3><p>Operating income decreased because product costs increased in this particular business during the period.</p>'''
    def handler(request):
        if request.url.path.endswith('company_tickers.json'):
            return httpx.Response(200,json={'0':{'ticker':'TEST','title':'TEST','cik_str':1}})
        if '/submissions/' in request.url.path:
            return httpx.Response(200,json={'filings':{'recent':{'form':['10-K'], 'accessionNumber':['0000000001-26-000001'], 'primaryDocument':['annual.htm'], 'filingDate':['2026-07-30'], 'reportDate':['2026-06-30']}}})
        return httpx.Response(200,text=html)
    client=SECClient('Unit tests tests@example.invalid', transport=httpx.MockTransport(handler))
    try:
        current=client.execute('search_sec_filings',SearchArgs(ticker='TEST',query='operating income',scope='company',fiscal_year=2026))
        assert current.status == 'no_data'  # Filing date does not rewrite the paragraph's years.
        older=client.execute('search_sec_filings',SearchArgs(ticker='TEST',query='operating income',scope='company',fiscal_year=2025))
        assert len(older.evidence) == 1
        assert older.evidence[0].scope == 'company'
        assert older.evidence[0].fiscal_years == [2025,2024]
        assert older.evidence[0].report_period == '2026-06-30'
        segment=client.execute('search_sec_filings',SearchArgs(ticker='TEST',query='operating income',scope='segment',fiscal_year=2025))
        assert segment.evidence[0].segment == 'Consumer Business'
    finally:client.close()


def test_empty_scope_filter_explains_how_to_recover(monkeypatch):
    from types import SimpleNamespace
    client=SECClient('tests tests@example.invalid')
    client.resolve=lambda ticker:('TEST','0000000001','TEST')
    def get(url,json=True):
        if 'submissions' in url:
            return {'filings':{'recent':{'form':['10-K'],'accessionNumber':['0000000001-25-000001'],'primaryDocument':['annual.htm'],'filingDate':['2025-02-01'],'reportDate':['2024-12-31']}}}
        return '<h2>Item 1A. Risk Factors</h2><p>Export restrictions could limit demand for products and reduce future growth by preventing sales to customers in restricted markets.</p>'
    client.get=get
    try:
        restricted=client.execute('get_sec_filings',SimpleNamespace(ticker='TEST',section='risks',scope='company'))
        assert restricted.status=='no_data'
        assert any('scope=all' in text for text in restricted.limitations)
        broad=client.execute('get_sec_filings',SimpleNamespace(ticker='TEST',section='risks',scope='all'))
        assert broad.status=='ok' and broad.evidence[0].scope=='unknown'
    finally: client.close()
