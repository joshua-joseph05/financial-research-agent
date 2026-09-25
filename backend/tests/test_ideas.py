from datetime import datetime,timezone,timedelta,date
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from app.ideas.models import IdeasRequest,IdeasPlan,IdeasDraft,StockIdea,Rationale,IdeasReview,IdeaCheck
from app.ideas.graph import run_ideas,SYSTEM
from app.ideas import market
from app.schemas import Evidence,Source,ToolResult
from app.providers.llm import SYSTEM as RESEARCH_SYSTEM
from app import api


class Registry:
    def descriptions(self):
        return [{'name':name,'description':name,'input_schema':{}} for name in ['get_financial_metric_history','calculate_financial_metrics','search_sec_filings']]

    def execute(self,call,observations):
        ticker=call.arguments['ticker']
        if call.name=='get_financials':
            end=(date.today()-timedelta(days=100)).isoformat()
            e=Evidence(id='financial:'+ticker,source_id='s:'+ticker,ticker=ticker,text='Annual revenue 100 USD.',metric='revenue',value='100',unit='USD',period=end,period_end=end)
        else:
            e=Evidence(id='passage:'+ticker,source_id='s:'+ticker,ticker=ticker,text='Competition could reduce demand for our products.',scope='unknown',section='risks')
        return ToolResult(status='ok',evidence=[e],sources=[Source(id='s:'+ticker,title='Filing',uri='https://www.sec.gov/test',synthetic=False)])


def shot(ticker,benchmark=False):
    e=Evidence(id='price:'+ticker,source_id='price:'+ticker,ticker=ticker,text='Prior-session close 100 USD.',metric='market_close',value='100',unit='USD')
    return {'symbol':ticker,'close':'100','currency':'USD','session':(date.today()-timedelta(days=1)).isoformat(),'fresh':True,'moves':{},'evidence':e.model_dump(),'source':Source(id=e.source_id,title='Price',uri='https://example.com',synthetic=False).model_dump()}


class Model:
    approve=True
    def respond(self,phase,context,schema,timeout):
        if phase=='ideas_investigate':
            from app.ideas.models import IdeasInvestigation
            return IdeasInvestigation(action='finish',reason='Sufficient test evidence.')
        if phase=='ideas_plan':return IdeasPlan(checks=['financial_performance','disclosed_risks'])
        tickers=context['request']['tickers']
        if phase=='ideas_recommend':
            return IdeasDraft(ideas=[StockIdea(ticker=t,action='consider_gradual_buying',reasons=[Rationale(text='Annual revenue was 100 USD.',evidence_ids=['financial:'+t])],risks=[Rationale(text='Competition could reduce demand.',evidence_ids=['passage:'+t])]) for t in tickers])
        return IdeasReview(checks=[IdeaCheck(ticker=t,supported=self.approve,explanation='Matches disclosed evidence.') for t in tickers])


def run(**kwargs):
    kwargs.setdefault('horizon','5_plus_years')
    kwargs.setdefault('risk_tolerance','medium')
    return run_ideas(IdeasRequest(tickers=['MSFT'],**kwargs),Model(),Registry(),snapshot_fn=shot)


def test_separate_workflow_can_return_conditional_buy_candidate():
    report=run()
    assert report['feature']=='stock_ideas'
    assert report['ideas'][0]['action']=='consider_gradual_buying'
    assert report['ideas'][0]['verified']
    assert 'not an investment recommender' in RESEARCH_SYSTEM
    assert SYSTEM!=RESEARCH_SYSTEM


@pytest.mark.parametrize('kwargs',[{'risk_tolerance':'low'},{'horizon':'under_3_years'}])
def test_preferences_override_buy_suggestion(kwargs):
    assert run(**kwargs)['ideas'][0]['action']=='watch'


@pytest.mark.parametrize('failure',['stale','stock_missing','benchmark_missing'])
def test_missing_or_stale_market_data_blocks_buying(failure):
    def snapshot(ticker,benchmark=False):
        if failure=='stock_missing' and not benchmark or failure=='benchmark_missing' and benchmark:raise ValueError('No quote')
        result=shot(ticker,benchmark)
        if failure=='stale':result['fresh']=False
        return result
    report=run_ideas(IdeasRequest(tickers=['MSFT']),Model(),Registry(),snapshot_fn=snapshot)
    assert report['ideas'][0]['action']=='watch'


def test_failed_review_hides_unverified_recommendation():
    model=Model();model.approve=False
    report=run_ideas(IdeasRequest(tickers=['MSFT']),model,Registry(),snapshot_fn=shot)
    assert not report['complete']
    assert report['ideas'][0]['action']=='watch'
    assert report['ideas'][0]['reasons']==[]


def test_missing_filings_block_buying():
    class Missing(Registry):
        def execute(self,call,observations):
            if call.name=='get_sec_filings':return ToolResult(status='no_data')
            return super().execute(call,observations)
    report=run_ideas(IdeasRequest(tickers=['MSFT']),Model(),Missing(),snapshot_fn=shot)
    assert report['ideas'][0]['action']=='watch'


def test_numerical_hallucination_fails_even_if_model_reviewer_approves():
    class Bad(Model):
        def respond(self,phase,*args,**kwargs):
            result=super().respond(phase,*args,**kwargs)
            if phase=='ideas_recommend':result.ideas[0].reasons[0].text='Annual revenue was 999 USD.'
            return result
    report=run_ideas(IdeasRequest(tickers=['MSFT']),Bad(),Registry(),snapshot_fn=shot)
    assert report['ideas'][0]['action']=='watch' and not report['complete']


def test_market_excludes_current_bar_and_computes_return(monkeypatch):
    now=datetime(2026,9,24,18,tzinfo=timezone.utc)
    timestamps=[int((now-timedelta(days=d)).timestamp()) for d in range(25,-1,-1)]
    payload={'chart':{'result':[{'meta':{'symbol':'SPY','instrumentType':'ETF','currency':'USD','exchangeTimezoneName':'America/New_York'},'timestamp':timestamps,'indicators':{'quote':[{'close':list(range(100,126))}]}}]}}
    monkeypatch.setattr(market,'public_get',lambda url:json.dumps(payload).encode())
    result=market.snapshot('SPY',True,now)
    assert result['close']=='124'
    assert result['session']=='2026-09-23'
    assert result['moves']['5_sessions']['percent']=='4.20'


def test_ideas_endpoint_streams_separately_and_uses_shared_busy_gate(monkeypatch):
    monkeypatch.setenv('SEC_USER_AGENT','tests test@example.invalid')
    monkeypatch.setattr(api,'perform_ideas',lambda payload,emit:{'feature':'stock_ideas','ideas':[]})
    with TestClient(api.app) as client:
        result=client.post('/stock-ideas',json={'tickers':['MSFT']})
        assert result.status_code==200
        assert json.loads(result.text.splitlines()[-1])['report']['feature']=='stock_ideas'
        monkeypatch.setattr(api,'busy',True)
        assert client.post('/stock-ideas',json={'tickers':['MSFT']}).status_code==409
        assert client.post('/research',json={'question':'MSFT risks','mode':'demo'}).status_code==409
    monkeypatch.setattr(api,'busy',False)


def test_inputs_reject_urls_and_limit_candidate_universe():
    with pytest.raises(ValueError):IdeasRequest(tickers=['https://example.com'])
    with pytest.raises(ValueError):IdeasRequest(tickers=['A','B','C','D','E'])
    assert IdeasRequest(tickers=['msft','MSFT']).tickers==['MSFT']


def test_entry_price_is_not_accepted_merely_because_it_matches_a_quote():
    from app.ideas.graph import validate_idea
    idea=StockIdea(ticker='MSFT',action='consider_gradual_buying',reasons=[Rationale(text='Buy at $100.',evidence_ids=['price:MSFT'])],risks=[Rationale(text='Competition could reduce demand.',evidence_ids=['passage:MSFT'])])
    issue=validate_idea(idea,{'price:MSFT':shot('MSFT')['evidence'],'passage:MSFT':{'id':'passage:MSFT','ticker':'MSFT','text':'Competition could reduce demand.'}})
    assert 'entry instruction' in issue


def test_revenue_citation_cannot_support_operating_income_claim():
    from app.ideas.graph import validate_idea
    e=Registry().execute(type('Call',(),{'name':'get_financials','arguments':{'ticker':'MSFT'}})(),{}).evidence[0].model_dump()
    risk={'id':'passage:MSFT','ticker':'MSFT','text':'Competition could reduce demand.'}
    idea=StockIdea(ticker='MSFT',action='consider_gradual_buying',reasons=[Rationale(text='Revenue and operating income increased.',evidence_ids=[e['id']])],risks=[Rationale(text='Competition could reduce demand.',evidence_ids=[risk['id']])])
    assert 'operating_income' in validate_idea(idea,{e['id']:e,risk['id']:risk})


def test_planner_cannot_invent_pre_retrieval_market_facts():
    with pytest.raises(ValueError):IdeasPlan(checks=['MSFT currently trades at 416.02'])


def test_growth_claim_requires_both_comparison_periods():
    from app.ideas.graph import validate_idea
    e=Registry().execute(type('Call',(),{'name':'get_financials','arguments':{'ticker':'MSFT'}})(),{}).evidence[0].model_dump()
    risk={'id':'passage:MSFT','ticker':'MSFT','text':'Competition could reduce demand.'}
    idea=StockIdea(ticker='MSFT',action='consider_gradual_buying',reasons=[Rationale(text='Revenue increased.',evidence_ids=[e['id']])],risks=[Rationale(text='Competition could reduce demand.',evidence_ids=[risk['id']])])
    assert 'both periods' in validate_idea(idea,{e['id']:e,risk['id']:risk})


@pytest.mark.parametrize('text,expected', [('in 7 years','5_plus_years'),('18 months','under_3_years'),('four years and six months','3_to_5_years'),('5-10 years','5_plus_years'),('when I retire','custom'),('maybe in 10 years','custom')])
def test_typed_horizon(text, expected):
    request=IdeasRequest(horizon='custom',horizon_text=text)
    assert request.horizon==expected
    assert request.horizon_text==text


def test_typed_short_or_unclear_horizon_blocks_buying():
    for text in ['18 months','when I retire']:
        report=run(horizon='custom',horizon_text=text)
        assert report['ideas'][0]['action']=='watch'


def test_custom_horizon_requires_text():
    with pytest.raises(ValueError):IdeasRequest(horizon='custom',horizon_text='  ')


def test_single_stock_question_uses_standalone_plan():
    report=run(question='What are the risks of investing in Microsoft?')
    assert report['plan']['focus']=='single_company_research'
    assert report['request']['question']=='What are the risks of investing in Microsoft?'
    assert [idea['ticker'] for idea in report['ideas']]==['MSFT']


@pytest.mark.parametrize('kind,tickers,mode', [('named_companies',['AAPL'],'question'),('discovery',['MSFT','AAPL'],'question'),('named_companies',['MSFT','AAPL'],'compare')])
def test_free_text_resolves_companies_before_research(kind,tickers,mode):
    from app.ideas.models import IdeasSelection
    class SelectingModel(Model):
        def respond(self,phase,context,schema,timeout):
            if phase=='ideas_select':return IdeasSelection(kind=kind,tickers=tickers)
            return super().respond(phase,context,schema,timeout)
    report=run_ideas(IdeasRequest(question='Help me find stock ideas',mode=mode),SelectingModel(),Registry(),snapshot_fn=shot)
    assert report['selection']['kind']==kind
    assert report['request']['tickers']==tickers
    assert [idea['ticker'] for idea in report['ideas']]==tickers


def test_comparison_cannot_invent_missing_peer():
    from app.ideas.models import IdeasSelection,IdeasClarification
    class SelectingModel(Model):
        def respond(self,phase,context,schema,timeout):
            assert phase=='ideas_select'
            return IdeasSelection(kind='discovery',tickers=['MSFT','AAPL'])
    with pytest.raises(IdeasClarification,match='at least two companies'):
        run_ideas(IdeasRequest(question='Compare something',mode='compare'),SelectingModel(),Registry(),snapshot_fn=shot)


def test_unresolved_question_stops_before_market_calls():
    from app.ideas.models import IdeasSelection,IdeasClarification
    class SelectingModel(Model):
        def respond(self,phase,context,schema,timeout):
            return IdeasSelection(kind='clarification',clarification='Which company do you mean?')
    with pytest.raises(IdeasClarification,match='Which company'):
        run_ideas(IdeasRequest(question='What about that company?'),SelectingModel(),Registry(),snapshot_fn=lambda *a,**k:pytest.fail('No market call expected'))


def test_selection_repairs_promise_and_continues_to_report():
    from app.ideas.models import IdeasSelection
    class SelectingModel(Model):
        selections=0
        def respond(self,phase,context,schema,timeout):
            if phase=='ideas_select':
                self.selections+=1
                if self.selections==1:
                    return IdeasSelection(kind='clarification',clarification='I will suggest a few established companies for you to research.')
                return IdeasSelection(kind='discovery',tickers=['MSFT','AAPL'])
            return super().respond(phase,context,schema,timeout)
    model=SelectingModel()
    report=run_ideas(IdeasRequest(question='What stocks could I research for long-term investing?'),model,Registry(),snapshot_fn=shot)
    assert model.selections==2
    assert len(report['ideas'])==2
    assert report['complete']


def test_repeated_selection_promise_is_not_shown_as_answer():
    from app.ideas.models import IdeasSelection,IdeasClarification
    class SelectingModel(Model):
        def respond(self,phase,context,schema,timeout):
            return IdeasSelection(kind='clarification',clarification='I will suggest companies.')
    with pytest.raises(IdeasClarification,match='could not select companies'):
        run_ideas(IdeasRequest(question='What stocks could I research?'),SelectingModel(),Registry(),snapshot_fn=shot)


@pytest.mark.parametrize('count',[8,12])
def test_wide_discovery_batches_evidence_and_reviews_all_candidates(count):
    from app.ideas.models import IdeasSelection
    candidates=['MSFT','AAPL','GOOGL','JNJ','JPM','CAT','XOM','PG','KO','LLY','NEE','WMT'][:count]
    class WideModel(Model):
        batches=[]
        def respond(self,phase,context,schema,timeout):
            if phase=='ideas_select':return IdeasSelection(kind='discovery',tickers=candidates)
            if phase in ('ideas_recommend','ideas_verify'):
                batch=context['request']['tickers']
                assert len(batch)<=3
                assert all(e['ticker'] in batch for e in context['observations'].values())
                self.batches.append((phase,batch))
            return super().respond(phase,context,schema,timeout)
    model=WideModel()
    report=run_ideas(IdeasRequest(question='What stocks could I research?',research_size=count),model,Registry(),snapshot_fn=shot)
    assert len(report['ideas'])==count
    assert report['complete']
    assert report['selection']['requested_count']==count
    assert report['selection']['selected_count']==count


def test_wide_discovery_failed_batch_keeps_other_results():
    from app.ideas.models import IdeasSelection
    class WideModel(Model):
        def respond(self,phase,context,schema,timeout):
            if phase=='ideas_select':return IdeasSelection(kind='discovery',tickers=['MSFT','AAPL','GOOGL','JNJ'])
            if phase=='ideas_recommend' and context['request']['tickers']==['JNJ']:raise TimeoutError()
            return super().respond(phase,context,schema,timeout)
    report=run_ideas(IdeasRequest(question='Stock ideas please'),WideModel(),Registry(),snapshot_fn=shot)
    assert len(report['ideas'])==4
    assert report['ideas'][0]['verified']
    assert report['ideas'][-1]['action']=='watch'
    assert not report['ideas'][-1]['verified']


def test_twenty_five_candidates_all_get_batched_reports():
    from app.ideas.models import IdeasSelection
    candidates=['AAA'+chr(65+i) for i in range(25)]
    class WideModel(Model):
        def respond(self,phase,context,schema,timeout):
            if phase=='ideas_select':return IdeasSelection(kind='discovery',tickers=candidates)
            if phase in ('ideas_recommend','ideas_verify'):
                assert len(context['request']['tickers'])<=3
            return super().respond(phase,context,schema,timeout)
    report=run_ideas(IdeasRequest(question='Find long term stock ideas',research_size=25),WideModel(),Registry(),snapshot_fn=shot)
    assert len(report['ideas'])==25
    assert report['complete']
    assert report['selection']['selected_count']==25


@pytest.mark.parametrize('count',[0,2,26,100])
def test_research_breadth_is_bounded(count):
    with pytest.raises(ValueError):IdeasRequest(research_size=count)


def test_investigation_chooses_tool_reads_result_then_finishes():
    from app.ideas.models import IdeasInvestigation
    class Investigator(Model):
        decisions=0
        def respond(self,phase,context,schema,timeout):
            if phase=='ideas_investigate':
                self.decisions+=1
                if self.decisions==1:
                    return IdeasInvestigation(action='tool',reason='Check cash flow history.',tool={'name':'get_financial_metric_history','arguments':{'ticker':'MSFT','metric':'operating_cash_flow','years':3}})
                assert context['previous_tool_calls'][0]['status']=='ok'
                return IdeasInvestigation(action='finish',reason='Reviewed the result.')
            return super().respond(phase,context,schema,timeout)
    model=Investigator()
    report=run_ideas(IdeasRequest(tickers=['MSFT']),model,Registry(),snapshot_fn=shot)
    assert model.decisions==2
    assert report['tool_calls'][0]['name']=='get_financial_metric_history'


def test_investigation_blocks_out_of_scope_companies_and_is_bounded():
    from app.ideas.models import IdeasInvestigation
    class Investigator(Model):
        decisions=0
        def respond(self,phase,context,schema,timeout):
            if phase=='ideas_investigate':
                self.decisions+=1
                return IdeasInvestigation(action='tool',reason='Investigate.',tool={'name':'get_financial_metric_history','arguments':{'ticker':'OTHER'}})
            return super().respond(phase,context,schema,timeout)
    model=Investigator()
    report=run_ideas(IdeasRequest(tickers=['MSFT']),model,Registry(),snapshot_fn=shot)
    assert model.decisions==4
    assert all(c['status']=='error' for c in report['tool_calls'])


def test_unverified_news_cannot_support_a_recommendation():
    from app.ideas.graph import validate_idea
    idea=StockIdea(ticker='MSFT',action='watch',reasons=[Rationale(text='Demand increased.',evidence_ids=['news:one'])],risks=[Rationale(text='Competition.',evidence_ids=['passage:one'])])
    assert 'Unverified' in validate_idea(idea,{})


def test_web_search_is_company_scoped_and_marks_leads(monkeypatch):
    from app.ideas.tools import execute
    from app.schemas import ToolCall
    from email.utils import format_datetime
    from urllib.parse import urlparse,parse_qs
    urls=[]
    def get(url):
        urls.append(url)
        return f'<rss><channel><item><title>New products announced</title><link>https://example.com/news</link><pubDate>{format_datetime(datetime.now(timezone.utc))}</pubDate></item></channel></rss>'.encode()
    monkeypatch.setattr('app.providers.research_sources.public_get',get)
    class SEC:
        def resolve(self,ticker):return ticker,'0000000001','Microsoft'
    registry=Registry();registry.sec=SEC()
    result=execute(registry,ToolCall(name='search_web',arguments={'ticker':'MSFT','query':'AI demand'}),{})
    query=parse_qs(urlparse(urls[0]).query)['q'][0]
    assert 'Microsoft' in query and 'AI demand' in query
    assert result.status=='ok'
    assert 'UNVERIFIED' in result.evidence[0].text


def test_general_question_routes_to_sourced_education_without_stocks(monkeypatch):
    from app.ideas.models import IdeasSelection,EducationalAnswer,EducationalSection,EducationalReview
    def guide(args):
        return ToolResult(status='ok',sources=[Source(id='guide',title='Education',uri='https://www.investor.gov',synthetic=False)],evidence=[Evidence(id='guide:one',source_id='guide',ticker='GENERAL',text='Diversification spreads investments across assets to reduce concentration risk.')])
    monkeypatch.setattr('app.providers.investing_guides.investing_guide',guide)
    class Educator(Model):
        def respond(self,phase,context,schema,timeout):
            if phase=='ideas_select':return IdeasSelection(kind='education',topics=['diversification'])
            if phase=='ideas_education':return EducationalAnswer(sections=[EducationalSection(title='Diversification',text='Diversification spreads investments across assets to reduce concentration risk.',evidence_ids=['guide:one'])])
            if phase=='ideas_education_review':return EducationalReview(supported=True,explanation='Supported.')
            pytest.fail('Unexpected company research')
    report=run_ideas(IdeasRequest(question='What is diversification?'),Educator(),Registry(),snapshot_fn=lambda *a,**kw:pytest.fail('No stock data needed'))
    assert report['feature']=='investment_education'
    assert report['complete'] and report['answer_sections']
    assert not report['ideas']


def test_question_only_comparison_and_explicit_preferences_are_inferred():
    from app.ideas.models import IdeasSelection
    class Selector(Model):
        def respond(self,phase,context,schema,timeout):
            if phase=='ideas_select':return IdeasSelection(kind='named_companies',tickers=['MSFT','AAPL'],user_horizon_text='18 months',user_risk_tolerance='low')
            return super().respond(phase,context,schema,timeout)
    report=run_ideas(IdeasRequest(question='Compare Microsoft and Apple. I need the money in 18 months and dislike losses.'),Selector(),Registry(),snapshot_fn=shot)
    assert report['request']['horizon']=='under_3_years'
    assert all(i['action']=='watch' for i in report['ideas'])
    assert len(report['ideas'])==2


def test_unspecified_preferences_do_not_assume_suitability():
    report=run_ideas(IdeasRequest(tickers=['MSFT']),Model(),Registry(),snapshot_fn=shot)
    assert report['ideas'][0]['action']=='watch'
    assert 'clarify' in report['ideas'][0]['caution']


def test_education_without_sources_does_not_generate_an_answer(monkeypatch):
    from app.ideas.models import IdeasSelection
    monkeypatch.setattr('app.providers.investing_guides.investing_guide',lambda args:ToolResult(status='no_data'))
    class Selector(Model):
        def respond(self,phase,context,schema,timeout):
            assert phase=='ideas_select'
            return IdeasSelection(kind='education',topics=['funds'])
    report=run_ideas(IdeasRequest(question='What is an ETF?'),Selector(),Registry(),snapshot_fn=shot)
    assert not report['complete']
    assert not report['answer_sections']


def test_investing_guides_extract_article_body_not_navigation(monkeypatch):
    from app.providers.investing_guides import investing_guide,GuideArgs
    text='A fund pools money from investors to purchase a collection of assets. Its holdings and fees vary.'
    monkeypatch.setattr('app.providers.investing_guides.public_get',lambda url:f'<nav><p>Unrelated navigation content with enough characters to pass the length filter.</p></nav><article><div class="article-body"><p>{text}</p></div></article>'.encode())
    result=investing_guide(GuideArgs(topic='funds'))
    assert [e.text for e in result.evidence]==[text]


def test_shared_budget_stops_calls_across_entire_workflow():
    from app.ideas.telemetry import MeteredModel,BudgetExceeded
    model=MeteredModel(Model(),4)
    report=run_ideas(IdeasRequest(tickers=['MSFT'],max_model_requests=4),model,Registry(),snapshot_fn=shot)
    assert model.used<=4
    with pytest.raises(BudgetExceeded):
        for _ in range(5):model.respond('ideas_plan',{},IdeasPlan,1)

