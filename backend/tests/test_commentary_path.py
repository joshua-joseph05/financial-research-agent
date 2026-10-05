import pytest
from app.assistant import AssistantRequest, run_assistant
from app.evaluation.sources import BenchmarkRegistry


class CommentaryModel:
    def __init__(self, only=True, covered=True):
        self.only, self.covered, self.phases = only, covered, []
    def respond(self, phase, context, schema, timeout):
        self.phases.append(phase)
        if phase == 'assistant_route':
            return schema(workflow='investment', reason='Review public opinions', commentary_only=self.only)
        if phase == 'ideas_select':
            return schema(kind='named_companies', tickers=['AAPL'], company_references=['Apple'])
        if phase == 'ideas_commentary_coverage':
            return schema(answers_question=self.covered, remaining_questions=[] if self.covered else ['Compare the cautious argument.'])
        raise AssertionError(f'Unnecessary financial/recommendation call: {phase}')


def brief(ticker='AAPL', status='reviewed_sample'):
    return dict(ticker=ticker, objective='Opinions', status=status, overall_sentiment='mixed',
                synthesis={'summary':{'text':'A bounded mixed sample.', 'argument_ids':[]}},
                arguments=[], sources=[], coverage={}, limitations=[])


def test_commentary_skips_financial_collection_and_purchase_drafting(monkeypatch):
    calls=[]
    def consult(args, model, registry, deadline, **kwargs):
        calls.append(args.ticker)
        assert kwargs['execution_profile']=='efficient' and kwargs['reserve']==1
        return brief()
    monkeypatch.setattr('app.ideas.sentiment.consult',consult)
    registry=BenchmarkRegistry()
    model=CommentaryModel()
    result=run_assistant(AssistantRequest(question='What are the optimistic and cautious opinions about Apple?', execution_profile='efficient'),lambda e:None,model,registry)
    assert calls==['AAPL']
    assert not registry.calls
    assert model.phases==['assistant_route','ideas_select','ideas_commentary_coverage']
    report=result['report']
    assert report['feature']=='sentiment_research' and report['complete']
    assert report['ideas']==[] and report['market'] is None
    assert report['sentiment_results'][0]['status']=='reviewed_sample'


@pytest.mark.parametrize('status,covered', [('insufficient_evidence',True),('reviewed_sample',False)])
def test_commentary_gaps_cannot_be_marked_complete(monkeypatch,status,covered):
    monkeypatch.setattr('app.ideas.sentiment.consult',lambda *a,**k:brief(status=status))
    result=run_assistant(AssistantRequest(question='Explain Apple commentary',execution_profile='efficient'),lambda e:None,CommentaryModel(covered=covered),BenchmarkRegistry())
    assert not result['report']['complete']
    assert result['report']['follow_up_questions']


def test_disabled_sentiment_does_not_call_specialist(monkeypatch):
    monkeypatch.setattr('app.ideas.sentiment.consult',lambda *a,**k:pytest.fail('Disabled'))
    result=run_assistant(AssistantRequest(question='Explain Apple commentary',execution_profile='efficient',sentiment_enabled=False),lambda e:None,CommentaryModel(),BenchmarkRegistry())
    assert not result['report']['complete']
    assert not result['report']['sentiment_results']


def test_mixed_request_retains_full_workflow(monkeypatch):
    options=[]
    monkeypatch.setattr('app.assistant.run_ideas',lambda *a,**k:options.append(k) or {})
    run_assistant(AssistantRequest(question='Compare Apple commentary with its cash flow and valuation before buying',execution_profile='efficient'),lambda e:None,CommentaryModel(only=False),BenchmarkRegistry())
    assert 'commentary_only' not in options[0]


def test_long_question_reaches_specialist_without_truncation(monkeypatch):
    question='What are opinions about Apple? '+('Include attributed optimistic and cautious views. '*8)
    def consult(args,*a,**k):
        assert args.objective==question.strip()
        return brief()
    monkeypatch.setattr('app.ideas.sentiment.consult',consult)
    result=run_assistant(AssistantRequest(question=question,execution_profile='efficient'),lambda e:None,CommentaryModel(),BenchmarkRegistry())
    assert result['report']['sentiment_results']


def test_coverage_failure_preserves_reviewed_brief_but_not_completion(monkeypatch):
    class FailedCoverage(CommentaryModel):
        def respond(self,phase,*a,**k):
            if phase=='ideas_commentary_coverage':raise TimeoutError('Offline')
            return super().respond(phase,*a,**k)
    monkeypatch.setattr('app.ideas.sentiment.consult',lambda *a,**k:brief())
    result=run_assistant(AssistantRequest(question='Explain Apple commentary',execution_profile='efficient'),lambda e:None,FailedCoverage(),BenchmarkRegistry())
    assert result['report']['sentiment_results']
    assert not result['report']['complete'] and result['report']['follow_up_questions']
