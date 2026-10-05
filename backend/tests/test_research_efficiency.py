from app.agent.graph import run_research
from app.evaluation.sources import BenchmarkRegistry
from app.schemas import Plan, Decision, ToolCall, EvidenceReview, Finding, Verification, ClaimCheck, Synthesis


class Model:
    def __init__(self):self.phases=[]
    def respond(self,phase,context,schema,timeout):
        self.phases.append(phase)
        if phase=='plan':return Plan(companies=['NVDA'],questions=['Disclosed growth risks?'],evidence_requirements=['filing_passages'])
        if phase=='investigate':return Decision(action='tool',reason='Read risk disclosure',tool=ToolCall(name='get_sec_filings',arguments={'ticker':'NVDA','section':'risks'}))
        if phase=='assess':return EvidenceReview(findings=[Finding(id='risk',text='Growth depends on a small group of customers.',kind='risk',evidence_ids=['passage:fixture:NVDA:risks']),Finding(id='risk2',text='Advanced packaging supply is constrained.',kind='risk',evidence_ids=['passage:fixture:NVDA:risks'])],open_questions=[],sufficient=True)
        if phase=='verify':return Verification(coverage='limited_by_sources',checks=[ClaimCheck(finding_id='risk',status='supported',explanation='Matches'),ClaimCheck(finding_id='risk2',status='insufficient',explanation='Test rejection')],unresolved_requirements=['Another requested part remains unanswered.'])
        return Synthesis(answer='',finding_ids=['risk'],limitations=[],follow_up_questions=[],unresolved_requirements=['Another requested part remains unanswered.'])


def test_python_assembly_preserves_review_and_unresolved_requirements():
    a,b=Model(),Model()
    standard=run_research('NVIDIA growth risks?',a,registry=BenchmarkRegistry())
    candidate=run_research('NVIDIA growth risks?',b,registry=BenchmarkRegistry(),execution_profile='efficient')
    assert len(b.phases)==len(a.phases)-1 and 'synthesize' not in b.phases
    assert candidate['report']['answer']==standard['report']['answer']
    assert [f['id'] for f in candidate['report']['findings']]==['risk']
    assert not candidate['report']['complete']
    assert candidate['draft']['unresolved_requirements']==['Another requested part remains unanswered.']


def test_plan_can_choose_first_tool_without_separate_decision_call():
    from app.agent.graph import EfficientPlan
    class Planned(Model):
        def respond(self,phase,context,schema,timeout):
            if phase=='plan':
                self.phases.append(phase)
                assert schema is EfficientPlan
                return EfficientPlan(companies=['NVDA'],questions=['Disclosed growth risks?'],evidence_requirements=['filing_passages'],initial_tool=ToolCall(name='get_sec_filings',arguments={'ticker':'NVDA','section':'risks'}))
            return super().respond(phase,context,schema,timeout)
    model=Planned();registry=BenchmarkRegistry()
    result=run_research('NVIDIA growth risks?',model,registry=registry,execution_profile='efficient')
    assert model.phases[:2]==['plan','assess']
    assert registry.calls[0]['name']=='get_sec_filings'
    assert result['report']['findings'][0]['id']=='risk'
    assert not result['report']['complete']
    assert 'verify' in model.phases


def test_efficient_plan_sees_schemas_and_review_separates_citations():
    from app.agent.graph import EfficientPlan
    class Scoped(Model):
        def respond(self,phase,context,schema,timeout):
            if phase=='plan':
                assert all('input_schema' in tool for tool in context['available_tools'])
                assert not any(t['name']=='calculate_financial_metrics' for t in context['available_tools'])
                return EfficientPlan(companies=['NVDA'],questions=['Disclosed risks?'],evidence_requirements=['filing_passages'],initial_tool=ToolCall(name='get_sec_filings',arguments={'ticker':'NVDA','section':'risks'}))
            if phase=='verify':
                assert 'observations' not in context
                assert all(set(item['cited_evidence'])==set(item['finding']['evidence_ids']) for item in context['claims_to_review'])
            return super().respond(phase,context,schema,timeout)
    report=run_research('NVIDIA growth risks?',Scoped(),registry=BenchmarkRegistry(),execution_profile='efficient')['report']
    assert report['findings'][0]['id']=='risk'


def test_business_tool_does_not_apply_financial_heading_filter():
    from app.agent.graph import EfficientPlan
    class Business(Model):
        def respond(self,phase,context,schema,timeout):
            if phase=='plan':return EfficientPlan(companies=['NVDA'],questions=['Business description?'],evidence_requirements=['filing_passages'],initial_tool=ToolCall(name='get_sec_filings',arguments={'ticker':'NVDA','section':'business','scope':'company'}))
            if phase=='assess':return EvidenceReview(findings=[],open_questions=[],sufficient=True)
            if phase=='verify':return Verification(coverage='limited_by_sources',checks=[],unresolved_requirements=['No finding produced in this test'])
            return super().respond(phase,context,schema,timeout)
    registry=BenchmarkRegistry()
    run_research('Describe NVIDIA business',Business(),registry=registry,execution_profile='efficient')
    assert registry.calls[0]['arguments']=={'ticker':'NVDA','section':'business'}
    assert any(e['section']=='business' for e in registry.calls[0]['result']['evidence'])


def test_unchanged_verification_is_reused_without_erasing_gaps():
    class Unresolved(Model):
        def respond(self,phase,context,schema,timeout):
            if phase=='investigate' and 'assess' in self.phases:
                self.phases.append(phase)
                return Decision(action='verify',reason='No additional evidence')
            if phase=='verify':
                self.phases.append(phase)
                return Verification(coverage='needs_more_evidence',checks=[ClaimCheck(finding_id='risk',status='supported',explanation='Supported'),ClaimCheck(finding_id='risk2',status='supported',explanation='Supported')],unresolved_requirements=['An essential requested fact is unavailable'])
            return super().respond(phase,context,schema,timeout)
    model=Unresolved()
    report=run_research('NVIDIA growth risks?',model,registry=BenchmarkRegistry(),execution_profile='efficient')['report']
    assert model.phases.count('verify')==1
    assert report['stop_reason']=='verification_no_progress'
    assert not report['complete']
    assert 'An essential requested fact is unavailable' in report['follow_up_questions']


def test_new_evidence_requires_a_fresh_verification():
    class Changes(Model):
        reviews=0
        def respond(self,phase,context,schema,timeout):
            if phase=='investigate' and self.reviews:
                self.phases.append(phase)
                return Decision(action='tool',reason='Retrieve additional data',tool=ToolCall(name='get_financials',arguments={'ticker':'NVDA'}))
            if phase=='verify':
                self.phases.append(phase);self.reviews+=1
                return Verification(coverage='needs_more_evidence' if self.reviews==1 else 'sufficient',checks=[ClaimCheck(finding_id=k,status='supported',explanation='Matches') for k in ('risk','risk2')],unresolved_requirements=['Need additional evidence'] if self.reviews==1 else [])
            return super().respond(phase,context,schema,timeout)
    model=Changes()
    report=run_research('NVIDIA growth risks?',model,registry=BenchmarkRegistry(),execution_profile='efficient')['report']
    assert model.reviews==2
    assert report['stop_reason']!='verification_no_progress'


def test_duplicate_recovery_gathers_missing_evidence_before_verifying():
    class Recover(Model):
        def __init__(self, repeat=False):
            super().__init__()
            self.decisions = 0
            self.repeat = repeat
        def respond(self, phase, context, schema, timeout):
            if phase == 'investigate':
                self.phases.append(phase)
                self.decisions += 1
                if self.decisions < 3 or self.repeat:
                    return Decision(action='tool', reason='Read risks', tool=ToolCall(name='get_sec_filings', arguments={'ticker':'NVDA','section':'risks'}))
                assert 'Duplicate call blocked' in context['feedback']
                return Decision(action='tool', reason='Read missing business description', tool=ToolCall(name='get_sec_filings', arguments={'ticker':'NVDA','section':'business'}))
            if phase == 'assess':
                result = super().respond(phase, context, schema, timeout)
                result.sufficient = self.decisions >= 3
                result.open_questions = [] if result.sufficient else ['Business description is still missing']
                return result
            return super().respond(phase, context, schema, timeout)
    model = Recover()
    registry = BenchmarkRegistry()
    result = run_research('NVIDIA risks and business?', model, registry=registry, execution_profile='efficient')
    assert model.phases == ['plan','investigate','assess','investigate','investigate','assess','verify']
    assert [c['arguments']['section'] for c in registry.calls] == ['risks','business']
    assert not result['report']['complete']  # The scripted reviewer still rejects risk2.
    repeating = Recover(repeat=True)
    result = run_research('NVIDIA risks and business?', repeating, registry=BenchmarkRegistry(), execution_profile='efficient')
    assert result['stop_reason'] == 'repeated_tool_call'
    assert repeating.phases.count('verify') == 1
    assert not result['report']['complete']


def test_python_verified_calculations_keep_source_lineage_for_coverage():
    from app.agent.graph import EfficientPlan
    class CalculationReview(Model):
        def respond(self, phase, context, schema, timeout):
            if phase == 'plan':
                return EfficientPlan(companies=['NVDA','MSFT'], questions=['Compare margins and growth'], evidence_requirements=['calculated_metrics'], initial_tool=ToolCall(name='compare_companies', arguments={'tickers':['NVDA','MSFT']}))
            if phase == 'assess':
                return EvidenceReview(findings=[], open_questions=[], sufficient=True)
            if phase == 'investigate':
                return Decision(action='verify', reason='Calculation results ready')
            if phase == 'verify':
                findings=context['python_verified_calculations']
                records=context['calculation_evidence']
                sources=context['calculation_sources']
                assert len(findings) >= 6
                assert any(e.get('metric') == 'revenue' and not e.get('operation') for e in records.values())
                for finding in findings:
                    assert set(finding['evidence_ids']) <= records.keys()
                for record in records.values():
                    assert set(record.get('input_ids',[])) <= records.keys()
                    assert record['source_id'] in sources
                assert 'observations' not in context
                return Verification(coverage='sufficient', checks=[])
            return super().respond(phase, context, schema, timeout)
    result=run_research('Compare Microsoft and NVIDIA revenue growth and operating margins', CalculationReview(), registry=BenchmarkRegistry(), execution_profile='efficient')
    assert not result['errors']
    assert len(result['report']['findings']) >= 6


def test_inconsistent_plan_gets_one_repair_before_retrieval():
    from app.agent.graph import EfficientPlan
    from app.agent.coverage import CoverageTarget
    class Repair(Model):
        plans=0
        def respond(self,phase,context,schema,timeout):
            if phase=='plan':
                self.plans+=1
                if self.plans==1:
                    CoverageTarget(ticker='NVDA',needs=['financial_values'],financial_metrics=[])
                assert context['plan_validation_errors']
                return EfficientPlan(companies=['NVDA'],questions=['Risks?'],evidence_requirements=['filing_passages'],initial_tool=ToolCall(name='get_sec_filings',arguments={'ticker':'NVDA','section':'risks'}))
            return super().respond(phase,context,schema,timeout)
    registry=BenchmarkRegistry();model=Repair()
    result=run_research('Explain NVIDIA risks',model,registry=registry,execution_profile='efficient')
    assert model.plans==2
    assert len(registry.calls)==1
    assert result['report']['findings']


def test_repeated_invalid_plan_stops_before_tools():
    from app.agent.coverage import CoverageTarget
    class Invalid(Model):
        plans=0
        def respond(self,phase,context,schema,timeout):
            assert phase=='plan'
            self.plans+=1
            CoverageTarget(ticker='NVDA',needs=['financial_values'],financial_metrics=[])
    registry=BenchmarkRegistry();model=Invalid()
    result=run_research('Explain NVIDIA risks',model,registry=registry,execution_profile='efficient')
    assert model.plans==2 and registry.calls==[]
    assert result['stop_reason']=='model_error'
    assert not result['report']['complete']
