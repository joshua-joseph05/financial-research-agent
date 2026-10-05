import time
import pytest
from app.ideas.sentiment import consult,ConsultArgs,Step,Findings,Argument,Review,Check,Synthesis,BriefClaim,handoff,overall
from app.ideas.telemetry import MeteredModel
from app.ideas.models import IdeasRequest,IdeasInvestigation
from app.ideas.graph import run_ideas
from test_ideas import Model,Registry,shot

QUOTE='Microsoft faces competitive pressure in cloud services.'
POSITIVE='Microsoft could benefit from growing demand for cloud services.'
ROWS={key:{'id':key,'url':f'https://{publisher}/news/example','title':'Company debate','published':'2026-09-24','publisher':publisher,'body':quote,'author':''} for key,publisher,quote in [('one','example.com',QUOTE),('two','other.com',POSITIVE)]}
class Sec:
    def resolve(self,t):return t,'1','Microsoft'
class LiveRegistry(Registry):sec=Sec()
class Worker:
    def __init__(self,quote=QUOTE,supported=True,unknown=False,summary_ok=True):self.n=0;self.quote=quote;self.supported=supported;self.unknown=unknown;self.summary_ok=summary_ok
    def respond(self,phase,context,schema,timeout):
        if phase.endswith('step'):
            self.n+=1
            return Step(action='read' if self.n==1 else 'finish',article_ids=['one','two'])
        if phase.endswith('extract'):
            return Findings(arguments=[Argument(article_id='one',kind='author_opinion',stance='bearish',point='The article raises cloud competition concerns.',quote=self.quote,importance='high'),Argument(article_id='two',kind='forecast',stance='bullish',point='The article expects demand to support growth.',quote=POSITIVE,importance='high')])
        if phase.endswith('synthesize'):
            ids=[a['id'] for a in context['arguments']]
            return Synthesis(summary=BriefClaim(text='The sample contains optimism about demand and concerns about competition.',argument_ids=['missing'] if self.unknown else ids),verification_tasks=[BriefClaim(text='Check cloud growth and competitive disclosures in filings.',argument_ids=ids)])
        return Review(checks=[Check(argument_id=a['id'],supported=self.supported) for a in context['arguments']],synthesis_supported=self.summary_ok)

def search(*args):return {'candidates':{k:{a:b for a,b in v.items() if a!='body'} for k,v in ROWS.items()},'attempts':[{'provider':'fixture','status':'ok'}]}
def run_worker(worker,limit=16,reader=None):
    return consult(ConsultArgs(ticker='MSFT',objective='Investigate expectations'),MeteredModel(worker,limit),LiveRegistry(),time.monotonic()+450,search_fn=search,read_fn=reader or (lambda r,*args:ROWS[r['id']]))

def test_sentiment_synthesizes_distinct_source_arguments():
    result=run_worker(Worker())
    assert result['arguments'][0]['quote']==QUOTE
    assert result['status']=='reviewed_sample'
    assert result['overall_sentiment']=='mixed'
    assert result['coverage']['articles_used']==2
    compact=handoff(result)
    assert compact['synthesis']['verification_tasks']
    assert 'body' not in str(compact)
    assert 'tool_calls' not in compact
    assert {a['kind'] for a in compact['evidence']}=={'author_opinion','forecast'}

@pytest.mark.parametrize('worker',[Worker(supported=False),Worker(unknown=True)])
def test_sentiment_withholds_unreviewed_synthesis(worker):
    result=run_worker(worker)
    assert not result['arguments']
    assert result['synthesis'] is None
    assert not handoff(result)['evidence']

def test_fabricated_quote_is_removed_before_synthesis():
    result=run_worker(Worker(quote='An invented statement absent from the article.'))
    assert all(a['quote']!= 'An invented statement absent from the article.' for a in result['arguments'])
    assert result['overall_sentiment']=='insufficient_evidence'

def test_sentiment_failure_and_budget_do_not_invent_opinions():
    def fail(*args):raise ValueError('Blocked')
    assert run_worker(Worker(),reader=fail)['status']=='insufficient_evidence'
    assert run_worker(Worker(),limit=2)['status']=='insufficient_evidence'

def test_one_source_failure_keeps_readable_sources():
    def read(row,*args):
        if row['id']=='one':raise ValueError('Blocked')
        return ROWS[row['id']]
    r=run_worker(Worker(),reader=read)
    assert r['coverage']['articles_read']==1
    assert r['coverage']['failed_reads']==1
    assert r['overall_sentiment']=='insufficient_evidence'

def test_many_quotes_from_one_publisher_do_not_establish_consensus():
    args=[{'kind':'author_opinion','stance':'bullish','source':{'publisher':'One source'}}]*10
    assert overall(args)=='insufficient_evidence'

def test_reported_facts_do_not_become_sentiment_votes():
    args=[{'kind':'reported_fact','stance':'bullish','source':{'publisher':p}} for p in ['a','b']]
    assert overall(args)=='insufficient_evidence'

@pytest.mark.parametrize('enabled',[True,False])
@pytest.mark.parametrize('profile',['standard','efficient'])
def test_lead_can_consult_and_use_compact_verified_handoff(monkeypatch,enabled,profile):
    calls=[];sentiment=run_worker(Worker())
    def fake(*args,**kwargs):calls.append(1);return sentiment
    monkeypatch.setattr('app.ideas.sentiment.consult',fake)
    class Lead(Model):
        n=0
        def respond(self,phase,context,schema,timeout):
            assert phase!='ideas_delegate'
            if phase=='ideas_investigate':
                names={s['name'] for s in context['available_tools']}
                assert ('consult_sentiment' in names)==(enabled and (profile=='standard' or self.n==0))
                if enabled and profile=='efficient' and self.n==0:
                    spec=next(s for s in context['available_tools'] if s['name']=='consult_sentiment')
                    assert spec['input_schema']['properties']['ticker']['enum']==['MSFT']
                self.n+=1
                if enabled and self.n==1:return IdeasInvestigation(action='tool',reason='Examine expectations',tool={'name':'consult_sentiment','arguments':{'ticker':'MSFT','objective':'Investigate expectations'}})
                if enabled:
                    brief=context['sentiment_findings'][0]
                    assert brief['synthesis']['verification_tasks']
                    assert 'tool_calls' not in brief
                    assert brief['overall_sentiment']=='mixed'
            if phase=='ideas_recommend' and enabled:
                if profile=='efficient':assert context['sentiment_context']==[]
                else:assert context['sentiment_context'][0]['synthesis']['summary']
            return super().respond(phase,context,schema,timeout)
    report=run_ideas(IdeasRequest(tickers=['MSFT'],sentiment_enabled=enabled),Lead(),Registry(),snapshot_fn=shot,execution_profile=profile)
    assert len(calls)==int(enabled)
    assert len(report['sentiment_results'])==int(enabled)
    assert 'specialist_results' not in report


def test_headline_only_finish_cannot_skip_initial_article_read():
    class Premature(Worker):
        def respond(self,phase,context,schema,timeout):
            if phase.endswith('step'):return Step(action='finish')
            return super().respond(phase,context,schema,timeout)
    result=run_worker(Premature())
    assert result['articles_read']==2
    assert any('Premature' in text for text in result['limitations'])


def test_duplicate_articles_cannot_inflate_source_coverage():
    def reader(row,*args):return {**ROWS[row['id']],'body':QUOTE}
    r=run_worker(Worker(),reader=reader)
    assert r['coverage']['duplicate_articles']==1
    assert r['coverage']['articles_read']==1
    assert r['overall_sentiment']=='insufficient_evidence'


def test_incomplete_review_cannot_release_a_summary():
    class Incomplete(Worker):
        def respond(self,phase,context,schema,timeout):
            if phase.endswith('review'):return Review(checks=[],synthesis_supported=True)
            return super().respond(phase,context,schema,timeout)
    assert run_worker(Incomplete())['synthesis'] is None


def test_failed_narrative_preserves_individually_reviewed_points():
    result=run_worker(Worker(summary_ok=False))
    assert result['status']=='reviewed_sample'
    assert result['overall_sentiment']=='mixed'
    assert result['synthesis']['disagreements']==[]
    assert 'free-form synthesis failed' in ' '.join(result['limitations'])


def test_truncated_synthesis_is_replaced_with_reviewed_points():
    class Truncated(Worker):
        def respond(self,phase,context,schema,timeout):
            result=super().respond(phase,context,schema,timeout)
            if phase.endswith('synthesize'):result.summary.text='The debate turns on whether the'
            return result
    r=run_worker(Truncated())
    assert r['synthesis']['summary']['text'].endswith('.')
    assert 'whether the' not in r['synthesis']['summary']['text']


def test_brief_selection_preserves_publishers_and_deduplicates_quotes():
    from app.ideas.sentiment import select_arguments
    items=[{'id':'a','importance':'high','source':{'publisher':'first'},'quote':'One two three four five six seven eight nine.'}, {'id':'b','importance':'high','source':{'publisher':'first'},'quote':'Another completely distinct investment argument from this same publisher.'}, {'id':'c','importance':'high','source':{'publisher':'second'},'quote':'A separate counterargument that differs from the first source.'}, {'id':'d','importance':'high','source':{'publisher':'third'},'quote':'One two three four five six seven eight nine.'}]
    result=select_arguments(items,2)
    assert [a['id'] for a in result]==['a','c']
    assert len(select_arguments(items))==3


def test_fallback_overall_cites_both_sides_even_when_bearish_point_is_late():
    from app.ideas.sentiment import evidence_brief
    items=[{'id':str(i),'kind':'author_opinion','stance':'bullish','source':{'publisher':'first'},'point':'An attributed positive argument.'} for i in range(5)]
    items.append({'id':'bear','kind':'author_opinion','stance':'bearish','source':{'publisher':'second'},'point':'An attributed negative argument.'})
    brief=evidence_brief(items)
    assert 'bear' in brief['summary']['argument_ids']


def test_lead_tool_decision_requires_inputs_and_constrains_available_tools():
    from app.providers.llm import response_schema
    with pytest.raises(ValueError):IdeasInvestigation(action='tool',reason='Missing input')
    with pytest.raises(ValueError):IdeasInvestigation(action='finish',reason='Invalid finish',tool={'name':'anything'})
    output=response_schema('ideas_investigate',{'available_tools':[{'name':'consult_sentiment','input_schema':ConsultArgs.model_json_schema()}]},IdeasInvestigation)
    choice=next(b for b in output['anyOf'] if b['properties']['action']['const']=='tool')
    assert choice['properties']['tool']['anyOf'][0]['properties']['name']['const']=='consult_sentiment'
    assert 'tool' in choice['required']


@pytest.mark.parametrize('supported', [True, False])
def test_efficient_sentiment_saves_synthesis_call_but_keeps_source_review(supported):
    results=[]; meters=[]
    for profile in ('standard','efficient'):
        meter=MeteredModel(Worker(supported=supported),16)
        result=consult(ConsultArgs(ticker='MSFT',objective='Investigate expectations'),meter,LiveRegistry(),time.monotonic()+450,search_fn=search,read_fn=lambda row,*args:ROWS[row['id']],execution_profile=profile)
        results.append(result);meters.append(meter)
    assert len(meters[1].calls)==len(meters[0].calls)-1
    assert any(c['phase'].endswith('review') for c in meters[1].calls)
    assert results[0]['arguments']==results[1]['arguments']
    assert results[1]['status']==('reviewed_sample' if supported else 'insufficient_evidence')
    if supported:
        assert results[1]['overall_sentiment']=='mixed'
        assert 'not market-wide consensus' in results[1]['synthesis']['summary']['text']
    else:
        assert results[1]['synthesis'] is None


def test_efficient_sentiment_rejects_fabricated_quotes():
    result=consult(ConsultArgs(ticker='MSFT',objective='Investigate expectations'),MeteredModel(Worker(quote='This fabricated quotation never appeared in the article.'),16),LiveRegistry(),time.monotonic()+450,search_fn=search,read_fn=lambda row,*args:ROWS[row['id']],execution_profile='efficient')
    assert len(result['arguments'])==1
    assert result['overall_sentiment']=='insufficient_evidence'
    assert result['arguments'][0]['kind']=='forecast'


def test_efficient_runtime_blocks_repeat_issuer_even_when_another_is_available(monkeypatch):
    consultations=[]
    sentiment=run_worker(Worker())
    def fake(*args,**kwargs):
        consultations.append(args[0].ticker)
        return sentiment
    monkeypatch.setattr('app.ideas.sentiment.consult',fake)
    class Lead(Model):
        n=0
        def respond(self,phase,context,schema,timeout):
            if phase=='ideas_investigate':
                self.n+=1
                if self.n==2:
                    spec=next(s for s in context['available_tools'] if s['name']=='consult_sentiment')
                    assert spec['input_schema']['properties']['ticker']['enum']==['NVDA']
                if self.n<=2:
                    # Emulate a provider violating the schema with different arguments.
                    return IdeasInvestigation(action='tool',reason='Check expectations',tool={'name':'consult_sentiment','arguments':{'ticker':'MSFT','objective':f'Investigate expectations {self.n}'}})
            return super().respond(phase,context,schema,timeout)
    report=run_ideas(IdeasRequest(tickers=['MSFT','NVDA']),Lead(),Registry(),snapshot_fn=shot,execution_profile='efficient')
    assert consultations==['MSFT']
    assert len(report['sentiment_results'])==1
    assert any(c.get('reason')=='Repeated tool call' for c in report['tool_calls'])


@pytest.mark.parametrize('placeholder',['empty','unknown','N/A','none'])
def test_missing_author_placeholder_keeps_exact_quotes_subject_to_review(placeholder):
    class UnknownAuthor(Worker):
        def respond(self,phase,context,schema,timeout):
            result=super().respond(phase,context,schema,timeout)
            if phase.endswith('extract'):
                result.arguments=[a.model_copy(update={'attribution':placeholder}) for a in result.arguments]
            if phase.endswith('review'):
                assert all(a['attribution']=='' for a in context['arguments'])
            return result
    def run(approve):
        return consult(ConsultArgs(ticker='MSFT',objective='Investigate expectations'),MeteredModel(UnknownAuthor(supported=approve),16),LiveRegistry(),time.monotonic()+450,search_fn=search,read_fn=lambda r,*args:ROWS[r['id']],execution_profile='efficient')
    assert len(run(True)['arguments'])==2
    assert not run(False)['arguments']


def test_speculation_does_not_supply_an_independent_sentiment_vote():
    arguments=[{'kind':'analyst_opinion','stance':'bearish','source':{'publisher':'news'}},
               {'kind':'speculation','stance':'bullish','source':{'publisher':'promotion'}}]
    assert overall(arguments)=='insufficient_evidence'


@pytest.mark.parametrize('failure',['invented_author','invented_quote'])
def test_placeholder_recovery_never_bypasses_real_source_checks(failure):
    class InvalidSource(Worker):
        def respond(self,phase,context,schema,timeout):
            result=super().respond(phase,context,schema,timeout)
            if phase.endswith('extract'):
                changes={'attribution':'Fabricated Expert'} if failure=='invented_author' else {'attribution':'empty','quote':'This invented statement is absent from both original articles.'}
                result.arguments=[a.model_copy(update=changes) for a in result.arguments]
            return result
    result=consult(ConsultArgs(ticker='MSFT',objective='Investigate expectations'),MeteredModel(InvalidSource(),16),LiveRegistry(),time.monotonic()+450,search_fn=search,read_fn=lambda r,*args:ROWS[r['id']],execution_profile='efficient')
    assert not result['arguments']
    assert result['synthesis'] is None


def test_attributed_speculative_analyst_view_is_not_erased_from_opinion_coverage():
    from app.ideas.sentiment import evidence_brief,attributed_opinion
    positive={'id':'positive','article_id':'one','kind':'speculation','stance':'bullish',
              'point':'The business could benefit from rising demand.',
              'quote':'Analyst Casey Chen believes the business could benefit from rising demand.',
              'attribution':'Casey Chen','source':{'publisher':'first'}}
    negative={'id':'negative','article_id':'two','kind':'analyst_opinion','stance':'bearish',
              'point':'Spending could increase costs.','quote':'Analyst Morgan Lee argues spending could increase costs.',
              'attribution':'Morgan Lee','source':{'publisher':'second'}}
    assert attributed_opinion(positive)
    assert overall([positive,negative])=='mixed'
    brief=evidence_brief([positive,negative])
    assert set(brief['summary']['argument_ids'])=={'positive','negative'}
    assert 'Casey Chen' in brief['bullish_arguments'][0]['text']
    assert 'Unverified source speculation' in brief['bullish_arguments'][0]['text']
    # A quoted attribution is not independently verified expertise or truth.
    assert positive['kind']=='speculation'


@pytest.mark.parametrize('quote,attribution',[
    ('A promotion guarantees that shares will double.',''),
    ('An article discusses analyst Casey Chen without quoting any opinion.','Casey Chen'),
    ('Analyst Someone Else believes the outlook is positive.','Casey Chen'),
])
def test_unattributed_or_unmatched_speculation_is_not_an_opinion_vote(quote,attribution):
    from app.ideas.sentiment import attributed_opinion
    arg={'kind':'speculation','stance':'bullish','quote':quote,'attribution':attribution,'source':{'publisher':'one'}}
    assert not attributed_opinion(arg)
    assert overall([arg,dict(arg,source={'publisher':'two'})])=='insufficient_evidence'
