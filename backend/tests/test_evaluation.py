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
