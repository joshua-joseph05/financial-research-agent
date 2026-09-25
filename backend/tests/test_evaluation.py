import pytest
from app.evaluation.summarize import summarize
from app.evaluation.fixtures import FixtureRegistry
from app.ideas.telemetry import MeteredModel, BudgetExceeded, http_attempt
from app.schemas import ToolCall


def test_retry_shares_request_budget():
    class Retrying:
        def respond(self, *args):
            http_attempt(False)
            http_attempt(True)
    meter = MeteredModel(Retrying(), 1)
    with pytest.raises(BudgetExceeded):
        meter.respond('test', {}, None, 1)
    assert meter.used == 1
    assert meter.http_attempts == 1
    assert meter.calls[0]['status'] == 'error'


def test_missing_fixture_does_not_invent_success():
    result = FixtureRegistry().execute(ToolCall(name='get_news', arguments={'ticker':'MSFT'}), {})
    assert result.status == 'no_data'
    assert not result.evidence


def test_summary_retains_failures_and_unassessed_scores():
    runs = [{'label':'a','workflow':'single','complete':True,'telemetry':{'request_budget_used':4,'elapsed_seconds':10}}, {'label':'b','workflow':'single','complete':False,'telemetry':{'request_budget_used':8,'elapsed_seconds':20}}]
    result = summarize(runs, [])['single']
    assert result['completion_rate'] == .5
    assert result['mean_requests'] == 6
    assert result['human_scores']['coverage_0_to_4'] == {'mean':None,'rated_runs':0}


def test_frozen_sentiment_has_both_views_and_untrusted_content():
    from app.evaluation.frozen_sources import discover, read, frozen_environment
    from app.ideas import graph
    found = discover('MSFT', 'Microsoft', 'outlook', 30, 0)
    assert len(found['candidates']) == 3
    assert all('body' not in c for c in found['candidates'].values())
    pages = [read(c, 30, 0) for c in found['candidates'].values()]
    assert any('forecast' in p['body'] for p in pages)
    assert any('cash flow' in p['body'] for p in pages)
    assert any('Ignore all previous' in p['body'] for p in pages)
    original = graph.date
    with frozen_environment():
        assert str(graph.date.today()) == '2026-09-23'
    assert graph.date is original


def test_audit_empty_answer_not_perfect_citations():
    from app.evaluation.metrics import audit
    assert audit({})['citation_resolution_rate'] is None
    result = audit({'ideas':[{'reasons':[{'evidence_ids':['missing']}], 'risks':[]}], 'evidence':[]})
    assert result['citation_resolution_rate'] == 0


@pytest.mark.parametrize('value', [-1, 5, True, '4', 1.5])
def test_invalid_human_scores_rejected(value):
    with pytest.raises(ValueError):
        summarize([{'label':'a','workflow':'single'}], [{'label':'a','scores':{'coverage_0_to_4':value}}])


def test_pairs_do_not_treat_missing_ratings_as_zero():
    from app.evaluation.summarize import paired_comparison
    runs = [{'label':w,'workflow':w,'case':'x','repeat':0,'complete':True,
             'telemetry':{'request_budget_used':n,'elapsed_seconds':n*2}} for w,n in [('single',3),('sentiment',5)]]
    reviews = [{'label':'single','scores':{'coverage_0_to_4':2}}, {'label':'sentiment','scores':{'coverage_0_to_4':4}}]
    result = paired_comparison(runs,reviews)
    assert result['pairs'][0]['extra_requests'] == 2
    assert result['mean_score_deltas']['coverage_0_to_4'] == {'mean_delta':2,'rated_pairs':1}
    assert result['mean_score_deltas']['citation_support_0_to_4']['mean_delta'] is None
    assert not result['pairs'][0]['sentiment_consulted']


def test_runner_keeps_failed_runs_and_protects_existing_output(tmp_path):
    import json
    from app.evaluation.compare import run_experiment
    class Model:
        model='test-model'
    def runner(request,model,registry,**kwargs):
        assert registry.sec.resolve('MSFT')[2] == 'Microsoft'
        if request.sentiment_enabled:
            raise TimeoutError('secret response must not be saved')
        return {'complete':False,'ideas':[],'evidence':[],'limitations':['missing data']}
    output=tmp_path/'experiment'
    cases=[{'id':'x','question':'Research Microsoft','tickers':['MSFT'],'rubric':['Check evidence']}]
    results=run_experiment(cases,output,model_factory=Model,runner=runner)
    assert len(results)==2
    assert sum('error' in r for r in results)==1
    assert 'secret response' not in (output/'results.json').read_text()
    assert json.loads((output/'manifest.json').read_text())['fixture_date']=='2026-09-23'
    with pytest.raises(FileExistsError):
        run_experiment(cases,output,model_factory=Model,runner=runner)
