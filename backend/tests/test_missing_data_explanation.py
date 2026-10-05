from app.agent.missing_data import missing_financial_explanation
from app.agent.graph import run_research,EfficientPlan
from app.schemas import ToolCall,Decision,EvidenceReview,Verification
from app.evaluation.sources import BenchmarkRegistry


def state(question='Calculate operating margin'):
    return {'question':question,'observations':{},'tool_calls':[{'name':'get_financials','result':{'status':'no_data'}}]}


def test_missing_margin_explains_formula_without_claiming_an_unpublished_or_future_period():
    text=missing_financial_explanation(state('Give Apple 2025 operating margin'))
    assert 'operating income and revenue for the same reporting period' in text
    assert 'multiplied by 100' in text
    assert 'No result was calculated' in text
    assert 'does not establish' in text
    assert 'prospective' not in text


def test_does_not_discard_retrieved_values_or_invent_a_retrieval_attempt():
    s=state();s['observations']={'one':{'value':'2','metric':'revenue'}}
    assert missing_financial_explanation(s) is None
    s=state();s['tool_calls']=[]
    assert missing_financial_explanation(s) is None
    s=state();s['tool_calls'][0]['name']='get_news'
    assert missing_financial_explanation(s) is None


def test_missing_report_is_useful_but_not_marked_as_a_completed_calculation():
    class Model:
        def respond(self,phase,context,schema,timeout):
            if phase=='plan':return EfficientPlan(companies=['AAPL'],questions=['2025 margin?'],evidence_requirements=['financial_values','calculated_metrics'],initial_tool=ToolCall(name='get_financials',arguments={'ticker':'AAPL'}))
            if phase=='assess':return EvidenceReview(findings=[],open_questions=['Data unavailable'],sufficient=False)
            if phase=='investigate':return Decision(action='verify',reason='No data')
            if phase=='verify':return Verification(coverage='limited_by_sources',checks=[],follow_up=['2025 is prospective.'],unresolved_requirements=['Missing figures'])
            raise AssertionError(phase)
    report=run_research('Calculate Apple 2025 operating margin',Model(),registry=BenchmarkRegistry('missing_financials'),execution_profile='efficient')['report']
    assert not report['complete'] and not report['findings']
    assert 'operating income divided by revenue' in report['answer']
    assert report['beginner_guide']['overview']==report['answer']
    assert 'prospective' not in ' '.join(report['follow_up_questions'])
