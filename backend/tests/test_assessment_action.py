import jsonschema
import pytest
from app.agent.graph import AssessmentAction, EfficientPlan, run_research, Limits
from app.evaluation.sources import BenchmarkRegistry
from app.providers.llm import response_schema
from app.schemas import ToolCall, Finding, Verification, ClaimCheck


class CombinedModel:
    def __init__(self): self.phases=[]
    def respond(self,phase,context,schema,timeout):
        self.phases.append(phase)
        if phase=='plan':
            return EfficientPlan(companies=['MSFT','NVDA'],questions=['Compare businesses'],evidence_requirements=['filing_passages'],initial_tool=ToolCall(name='get_sec_filings',arguments={'ticker':'MSFT','section':'business'}))
        if phase=='assess':
            assert schema is AssessmentAction
            assert context['available_tools'] and context['previous_calls']
            last=context['new_evidence_ids'][0]
            ticker=context['observations'][last]['ticker']
            return AssessmentAction(findings=[Finding(id='claim_'+ticker.lower(),text=context['observations'][last]['text'],evidence_ids=[last])],open_questions=[] if ticker=='NVDA' else ['NVIDIA business'],sufficient=ticker=='NVDA',next_action='verify' if ticker=='NVDA' else 'tool',next_tool=None if ticker=='NVDA' else ToolCall(name='get_sec_filings',arguments={'ticker':'NVDA','section':'business'}))
        if phase=='verify':
            return Verification(coverage='sufficient',checks=[ClaimCheck(finding_id=item['finding']['id'],status='supported',explanation='Matches cited business passage') for item in context['claims_to_review']],unresolved_requirements=[])
        raise AssertionError('Unnecessary model phase: '+phase)


def test_assessment_selects_next_tool_without_extra_investigation_call():
    model=CombinedModel()
    state=run_research('Compare Microsoft and NVIDIA businesses',model,registry=BenchmarkRegistry(),execution_profile='efficient')
    assert model.phases==['plan','assess','assess','verify']
    assert state['report']['complete']
    assert {e['ticker'] for e in state['report']['evidence']}=={'MSFT','NVDA'}
    assert len(state['tool_calls'])==2
    assert state['iteration_count']==2


def test_combined_action_still_respects_tool_budget_and_verifies():
    model=CombinedModel()
    state=run_research('Compare Microsoft and NVIDIA businesses',model,registry=BenchmarkRegistry(),execution_profile='efficient',limits=Limits(max_tool_calls=1))
    assert len(state['tool_calls'])==1
    assert model.phases==['plan','assess','verify']
    assert not state['report']['complete']
    assert state['stop_reason']=='tool_budget'


def test_assessment_tool_schema_rejects_invented_tools():
    context={'available_tools':BenchmarkRegistry().descriptions({}),'observations':{}}
    schema=response_schema('assess',context,AssessmentAction)
    response={'findings':[],'open_questions':[],'sufficient':False,'next_action':'tool','next_tool':{'name':'get_sec_filings','arguments':{'ticker':'NVDA','section':'business'}}}
    jsonschema.validate(response,schema)
    response['next_tool']['name']='invented_tool'
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(response,schema)


def test_numeric_fast_path_still_verifies_and_ignores_empty_requirement_marker():
    from app.agent.coverage import CoverageTarget
    class NumericModel:
        def __init__(self):self.phases=[]
        def respond(self,phase,context,schema,timeout):
            self.phases.append(phase)
            if phase=='plan':
                return EfficientPlan(companies=['NVDA'],questions=['Revenue and operating income'],evidence_requirements=['financial_values'],coverage_targets=[CoverageTarget(ticker='NVDA',needs=['financial_values'])],initial_tool=ToolCall(name='get_financials',arguments={'ticker':'NVDA'}))
            if phase=='verify':
                assert len(context['python_verified_calculations'])==4
                return Verification(coverage='sufficient',checks=[],unresolved_requirements=['None'],follow_up=['N/A'])
            raise AssertionError(phase)
    model=NumericModel()
    state=run_research('NVIDIA revenue and operating income for 2025?',model,registry=BenchmarkRegistry(),execution_profile='efficient')
    assert model.phases==['plan','verify']
    assert state['report']['complete']
    assert len(state['report']['findings'])==4
    assert state['report']['follow_up_questions']==[]


@pytest.mark.parametrize('action,tool', [('tool',None),('verify',{'name':'get_sec_filings','arguments':{'ticker':'NVDA','section':'business'}})])
def test_response_schema_forbids_contradictory_next_action(action,tool):
    schema=response_schema('assess',{'available_tools':BenchmarkRegistry().descriptions({}),'observations':{}},AssessmentAction)
    response={'findings':[],'open_questions':[],'sufficient':True,'next_action':action,'next_tool':tool}
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(response,schema)


def test_runtime_keeps_supported_finding_when_provider_ignores_action_schema():
    class MalformedModel(CombinedModel):
        def respond(self,phase,context,schema,timeout):
            if phase=='assess':
                self.phases.append(phase)
                key=context['new_evidence_ids'][0]
                return AssessmentAction(findings=[Finding(id='claim_business',text=context['observations'][key]['text'],evidence_ids=[key])],open_questions=['No open questions.'],sufficient=True,next_action='tool',next_tool=None)
            return super().respond(phase,context,schema,timeout)
    model=MalformedModel()
    state=run_research('Describe Microsoft business',model,registry=BenchmarkRegistry(),execution_profile='efficient')
    assert model.phases==['plan','assess','verify']
    assert state['report']['complete']
    assert len(state['report']['findings'])==1
    assert not state['errors']


def test_sufficient_assessment_does_not_execute_redundant_tool_before_verifying():
    class RedundantModel(CombinedModel):
        def respond(self,phase,context,schema,timeout):
            if phase=='assess':
                self.phases.append(phase)
                key=context['new_evidence_ids'][0]
                return AssessmentAction(findings=[Finding(id='claim_business',text=context['observations'][key]['text'],evidence_ids=[key])],open_questions=[],sufficient=True,next_action='tool',next_tool=ToolCall(name='get_sec_filings',arguments={'ticker':'MSFT','section':'business'}))
            return super().respond(phase,context,schema,timeout)
    model=RedundantModel()
    state=run_research('Describe Microsoft business',model,registry=BenchmarkRegistry(),execution_profile='efficient')
    assert model.phases==['plan','assess','verify']
    assert len(state['tool_calls'])==1
    assert state['report']['complete']
