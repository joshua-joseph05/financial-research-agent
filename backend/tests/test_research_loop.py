from app.agent.graph import Limits, run_research
from app.providers.demo import DemoModel
from app.schemas import ClaimCheck, Decision, EvidenceReview, Finding, Plan, Synthesis, ToolCall, Verification


class ScriptedModel:
    """Controlled responses test orchestration without making any LLM calls."""
    def __init__(self, decisions, verifications=None, answer=None):
        self.decisions = iter(decisions)
        self.verifications = iter(verifications) if verifications else None
        self.answer = answer

    def respond(self, phase, context, schema, timeout):
        if phase == "plan":
            return Plan(companies=["NVDA"], questions=["Growth risks?"])
        if phase == "investigate":
            return next(self.decisions)
        if phase == "assess":
            return EvidenceReview(findings=[], open_questions=[], sufficient=False)
        if phase == "verify":
            if self.verifications:
                return next(self.verifications)
            return Verification(coverage="sufficient", checks=[ClaimCheck(finding_id=f["id"], status="supported", explanation="Test assertion")
                                        for f in context["findings"]])
        return Synthesis(answer=self.answer or "Synthetic research findings.",
            finding_ids=[f["id"] for f in context["findings"]], limitations=[], follow_up_questions=[])


def tool(name="get_sec_filings", **arguments):
    return Decision(action="tool", reason="Retrieve evidence", tool=ToolCall(name=name, arguments=arguments or {"ticker": "NVDA", "section": "risks"}))


def done(evidence="NVDA:section:risks", text="Customer concentration is a synthetic risk."):
    return Decision(action="verify", reason="Check evidence", findings=[Finding(id="risk", text=text, evidence_ids=[evidence])])


def test_demo_questions_take_different_paths_and_follow_new_evidence():
    risk = run_research("NVIDIA growth risks?", DemoModel())
    margin = run_research("Why did Microsoft margins change?", DemoModel())
    assert [t["name"] for t in risk["tool_calls"]] == ["get_sec_filings", "search_sec_filings"]
    assert risk["tool_calls"][1]["arguments"]["query"] == "packaging"
    assert any(t["name"] == "calculate_financial_metrics" for t in margin["tool_calls"])
    assert risk["report"]["complete"] and margin["report"]["complete"]
    assert margin["report"]["synthetic"]
    assert any(e["value"] == "5.0000" for e in margin["report"]["evidence"])


def test_verifier_can_send_agent_back_for_more_evidence():
    checks = [ClaimCheck(finding_id="risk", status="supported", explanation="Matches passage")]
    model = ScriptedModel([tool(), done(), tool("search_sec_filings", ticker="NVDA", query="packaging"), done()],
        [Verification(coverage="needs_more_evidence", checks=checks, follow_up=["Investigate capacity"]), Verification(coverage="sufficient", checks=checks)])
    state = run_research("Growth risks?", model)
    assert len(state["tool_calls"]) == 2
    assert state["verification_count"] == 2
    assert state["report"]["complete"]


def test_unknown_citation_is_removed_even_if_model_approves():
    state = run_research("Risks?", ScriptedModel([tool(), done("invented")]), Limits(max_verifications=1))
    assert not state["report"]["findings"]
    assert not state["report"]["complete"]
    assert any("Unknown evidence" in s for s in state["report"]["limitations"])


def test_unmatched_numerical_finding_is_rejected():
    state = run_research("Risks?", ScriptedModel([tool(), done(text="Revenue is 9999 million.")]), Limits(max_verifications=1))
    assert not state["report"]["findings"]


def test_unmatched_summary_number_is_replaced():
    state = run_research("Risks?", ScriptedModel([tool(), done()], answer="Revenue reached 9999 million."))
    assert "9999" not in state["report"]["answer"]
    assert not state["report"]["complete"]


def test_tool_cap_still_evaluates_last_observation():
    state = run_research("Risks?", ScriptedModel([tool(), done()]), Limits(max_tool_calls=1))
    assert len(state["tool_calls"]) == 1
    assert state["report"]["findings"]
    assert state["stop_reason"] == "tool_budget"
    assert not state["report"]["complete"]


def test_repeated_call_terminates():
    state = run_research("Risks?", ScriptedModel([tool(), tool(), tool()]))
    assert len(state["tool_calls"]) == 1
    assert state["stop_reason"] == "repeated_tool_call"


def test_invalid_tool_returns_error_then_agent_recovers():
    state = run_research("Risks?", ScriptedModel([tool("unknown_tool", ticker="NVDA"), tool(), done()]))
    assert state["tool_calls"][0]["result"]["status"] == "error"
    assert state["report"]["complete"]


def test_state_does_not_leak_across_runs():
    first = run_research("NVIDIA risks", DemoModel())
    second = run_research("Microsoft margins", DemoModel())
    assert all(e["ticker"] == "MSFT" for e in second["observations"].values())
    assert all(e["ticker"] == "NVDA" for e in first["observations"].values())


def test_model_error_returns_explicit_incomplete_report():
    class Broken:
        def respond(self, *args, **kwargs):
            raise RuntimeError("Unavailable")
    state = run_research("Risks?", Broken())
    assert not state["report"]["complete"]
    assert state["stop_reason"] == "model_error"
    assert not state["report"]["findings"]


def test_deadline_returns_partial_report_without_infinite_loop():
    times = iter([0, 200])
    def clock():
        return next(times, 200)
    state = run_research("Risks?", DemoModel(), Limits(seconds=180, finalization_reserve=30), clock=clock)
    assert not state["report"]["complete"]
    assert not state["tool_calls"]


def test_iteration_limit_stops_unique_requests():
    state = run_research("Risks?", ScriptedModel([tool()]), Limits(max_iterations=1))
    assert state["stop_reason"] == "iteration_budget"
    assert state["iteration_count"] == 1


def test_duplicate_call_is_not_executed_and_agent_can_recover():
    state = run_research('Risks?', ScriptedModel([tool(), tool(), done()]))
    assert len(state['tool_calls']) == 1
    assert state['duplicate_count'] == 1
    assert state['report']['complete']
    assert state['report']['findings']


def test_company_alias_cannot_bypass_duplicate_guard():
    state = run_research('Risks?', ScriptedModel([
        tool(ticker='NVIDIA', section='RISKS'), tool(ticker='nvda', section='risks'), done()]))
    assert len(state['tool_calls']) == 1
    assert state['duplicate_count'] == 1
    assert state['report']['complete']


def test_findings_survive_later_decision_with_empty_findings():
    first = done()
    first.action = 'tool'
    first.tool = ToolCall(name='search_sec_filings', arguments={'ticker':'NVDA','query':'packaging'})
    state = run_research('Risks?', ScriptedModel([tool(), first, Decision(action='verify', reason='Ready')]))
    assert [f['id'] for f in state['report']['findings']] == ['risk']
    assert state['report']['complete']


def test_assessment_can_finish_without_another_selection_call():
    class Assessing(ScriptedModel):
        def respond(self, phase, context, schema, timeout):
            if phase == 'assess':
                return EvidenceReview(findings=done().findings, open_questions=[], sufficient=True)
            return super().respond(phase, context, schema, timeout)
    state = run_research('Risks?', Assessing([tool()]))
    assert state['iteration_count'] == 1
    assert state['report']['complete']


def test_assessment_reviews_final_result_at_iteration_cap():
    class Assessing(ScriptedModel):
        def respond(self, phase, context, schema, timeout):
            if phase == 'assess':
                return EvidenceReview(findings=done().findings, open_questions=[], sufficient=True)
            return super().respond(phase, context, schema, timeout)
    state = run_research('Risks?', Assessing([tool()]), Limits(max_iterations=1))
    assert state['report']['findings']
    assert state['stop_reason'] == 'iteration_budget'
    assert not state['report']['complete']


def test_context_contains_evidence_once_and_no_tools_for_synthesis():
    class Capturing(ScriptedModel):
        def respond(self, phase, context, schema, timeout):
            if phase == 'investigate' and context['previous_calls']:
                assert 'result' not in context['previous_calls'][0]
                assert 'observations' in context
            if phase in ('assess','synthesize'):
                assert 'available_tools' not in context
            if phase in ('plan', 'verify'):
                assert context['available_tools']
                assert all('input_schema' not in tool for tool in context['available_tools'])
            return super().respond(phase, context, schema, timeout)
    state = run_research('Risks?', Capturing([tool(), done()]))
    assert state['report']['complete']


def test_verification_can_resolve_an_earlier_open_question():
    class Assessing(ScriptedModel):
        def respond(self, phase, context, schema, timeout):
            if phase == 'assess':
                return EvidenceReview(findings=done().findings,
                    open_questions=['Which customer risks are disclosed?'], sufficient=False)
            return super().respond(phase, context, schema, timeout)
    state = run_research('Risks?', Assessing([tool(), Decision(action='verify', reason='Enough evidence')]))
    assert state['report']['complete']
    assert state['open_questions'] == []


def test_assessment_failure_does_not_lose_existing_findings_or_claim_completion():
    class FailingAssessment(ScriptedModel):
        def respond(self, phase, context, schema, timeout):
            if phase == 'assess':
                raise ValueError('malformed output')
            return super().respond(phase, context, schema, timeout)
    state = run_research('Risks?', FailingAssessment([tool()]))
    assert state['stop_reason'] == 'assessment_error'
    assert not state['report']['complete']


def test_verification_budget_still_caps_unresolved_followups():
    checks=[ClaimCheck(finding_id='risk', status='supported', explanation='Matches')]
    model=ScriptedModel([tool(),done(),done()], [
        Verification(coverage="needs_more_evidence", checks=checks, follow_up=['Missing material evidence']),
        Verification(coverage="needs_more_evidence", checks=checks, follow_up=['Still missing material evidence'])])
    state=run_research('Risks?',model)
    assert state['verification_count'] == 2
    assert state['stop_reason'] == 'verification_budget'
    assert state['report']['findings']
    assert not state['report']['complete']


def test_verifier_can_request_wording_correction_without_refetching_evidence():
    class Correcting(ScriptedModel):
        def respond(self, phase, context, schema, timeout):
            if phase == 'assess':
                text='Customer concentration guarantees failure.' if not context['verification'] else 'Customer concentration is a synthetic risk.'
                return EvidenceReview(findings=done(text=text).findings,open_questions=[],sufficient=True)
            return super().respond(phase,context,schema,timeout)
    state=run_research('Risks?',Correcting([tool()], [
        Verification(coverage='needs_more_evidence', checks=[ClaimCheck(finding_id='risk', status='insufficient', explanation='Risk is not a guaranteed outcome')]),
        Verification(coverage='sufficient', checks=[ClaimCheck(finding_id='risk', status='supported', explanation='Qualified risk matches source')])]))
    assert len(state['tool_calls']) == 1
    assert state['verification_count'] == 2
    assert state['report']['complete']
    assert 'guarantees' not in state['report']['findings'][0]['text']


def test_known_citation_hash_is_not_treated_as_a_numerical_claim():
    from app.agent.graph import numeric_check
    records=[{'id':'calc:55fe1f5422f0','text':'Operating margin 30 percent','value':'30','period':'2024'}]
    assert numeric_check('The 2024 operating margin was 30 percent (calc:55fe1f5422f0).',records)
    assert not numeric_check('The operating margin was 99 percent (calc:55fe1f5422f0).',records)
    assert not numeric_check('The operating margin was 30 percent (calc:999unknown).',records)


def test_different_search_with_same_evidence_goes_to_verification():
    first=done()
    first.action='tool'
    first.tool=ToolCall(name='search_sec_filings',arguments={'ticker':'NVDA','query':'small'})
    state=run_research('Risks?',ScriptedModel([tool(),first]))
    assert len(state['tool_calls']) == 2
    assert state['no_progress_count'] == 1
    assert state['new_evidence_ids'] == []
    assert state['report']['complete']


def test_repeated_missing_data_stops_with_explicit_gap():
    state=run_research('Unknown company?',ScriptedModel([
        tool('get_financials',ticker='UNKNOWN'),
        tool('get_sec_filings',ticker='UNKNOWN')]))
    assert state['stop_reason'] == 'no_new_evidence'
    assert not state['report']['complete']
    assert not state['report']['findings']
    assert any('Fixture coverage' in s for s in state['report']['limitations'])


def test_duplicate_with_findings_triggers_coverage_review_before_more_tools():
    class Reviewing(ScriptedModel):
        def respond(self,phase,context,schema,timeout):
            if phase == 'assess':
                return EvidenceReview(findings=done().findings,open_questions=['More detail?'],sufficient=False)
            if phase == 'verify':
                assert 'plan' not in context
                assert 'open_questions' not in context
            return super().respond(phase,context,schema,timeout)
    state=run_research('Risks?',Reviewing([tool(),tool()]))
    assert len(state['tool_calls']) == 1
    assert state['duplicate_count'] == 1
    assert state['report']['complete']


def test_optional_followups_do_not_reopen_completed_research():
    checks=[ClaimCheck(finding_id='risk',status='supported',explanation='Matches source')]
    model=ScriptedModel([tool(),done()],[Verification(coverage='sufficient', checks=checks,
        follow_up=['Consider a deeper product comparison in future research'])])
    state=run_research('Risks?',model)
    assert state['verification_count'] == 1
    assert state['report']['complete']
    assert state['report']['follow_up_questions']


def test_unavailable_material_evidence_stops_without_search_loop():
    checks=[ClaimCheck(finding_id='risk',status='supported',explanation='Matches source')]
    model=ScriptedModel([tool(),done()],[Verification(coverage='limited_by_sources', checks=checks,
        follow_up=['Detailed segment data is unavailable in these fixtures'])])
    state=run_research('Risks?',model)
    assert state['verification_count'] == 1
    assert state['stop_reason'] == 'source_limit'
    assert not state['report']['complete']
    assert state['report']['findings']


def test_source_limit_with_no_findings_does_not_trigger_another_investigation():
    model=ScriptedModel([Decision(action='verify',reason='Sources cannot answer')],[
        Verification(coverage='limited_by_sources',checks=[],follow_up=['Requested data unavailable'])])
    state=run_research('Unavailable data?',model)
    assert state['stop_reason'] == 'source_limit'
    assert state['verification_count'] == 1
    assert not state['report']['findings']
    assert not state['report']['complete']


def test_assessment_rejects_invented_numbers_before_next_tool_choice():
    class InventedNumberModel(ScriptedModel):
        def respond(self, phase, context, schema, timeout):
            if phase == 'assess':
                return EvidenceReview(findings=[Finding(id='invented', text='Revenue was 999999 dollars.', evidence_ids=['NVDA:section:risks'])], open_questions=[], sufficient=True)
            if phase == 'investigate' and context['observations']:
                assert context['findings'] == []
                assert 'Numerical claim does not match' in context['feedback']
                assert any('calculate_financial_metrics' in q for q in context['open_questions'])
            return super().respond(phase, context, schema, timeout)
    state = run_research('Growth risks?', InventedNumberModel([tool(), done()]))
    assert all(f['id'] != 'invented' for f in state['report']['findings'])


def test_change_citation_checks_nested_calculations_and_both_periods():
    from app.agent.graph import structural_check
    from app.tools.registry import ToolRegistry
    registry = ToolRegistry()
    raw = registry.execute(ToolCall(name='get_financials', arguments={'ticker':'MSFT'}), {})
    observations = {e.id:e.model_dump() for e in raw.evidence}
    comparison = registry.execute(ToolCall(name='calculate_financial_metrics', arguments={
        'operation':'compare_operating_margins', 'evidence_ids':[
            'MSFT:2025:operating_income','MSFT:2025:revenue','MSFT:2024:operating_income','MSFT:2024:revenue']}), observations)
    observations.update({e.id:e.model_dump() for e in comparison.evidence})
    state = {'observations':observations, 'sources':{s.id:s.model_dump() for s in raw.sources+comparison.sources}}
    finding = Finding(id='change', text='Margin increased 5 percentage points from 2024 to 2025.', evidence_ids=[comparison.evidence[-1].id]).model_dump()
    assert structural_check(finding, state) is None
    observations['MSFT:2025:operating_income']['value'] = '120'
    assert structural_check(finding, state) == 'Calculation failed reproduction'


def test_plan_evidence_requirements_prevent_premature_completion():
    class RequiresFinancials(ScriptedModel):
        def respond(self, phase, context, schema, timeout):
            if phase == 'plan':
                return Plan(companies=['NVDA'], questions=['Risks and financial context?'], evidence_requirements=['financial_values','filing_passages'])
            return super().respond(phase, context, schema, timeout)
    model = RequiresFinancials([tool(), done(), tool('get_financials', ticker='NVDA'), done()])
    state = run_research('Explain risks with financial context.', model)
    assert state['verification_count'] == 2
    assert [c['name'] for c in state['tool_calls']] == ['get_sec_filings','get_financials']
    assert state['report']['complete']


def test_historical_plan_normalizes_required_evidence_for_fixture_mode():
    class HistoricalDemo(DemoModel):
        def respond(self, phase, context, schema, timeout):
            if phase == 'plan':
                return Plan(answer_type='historical_explanation', companies=['MSFT'], questions=['Why did margins change?'])
            return super().respond(phase, context, schema, timeout)
    state=run_research('Why did Microsoft margins change?', HistoricalDemo())
    assert state['plan']['evidence_requirements'] == ['financial_values','calculated_metrics','filing_passages']
    assert state['report']['complete']


def test_descriptive_risks_do_not_require_historical_change_explanation():
    class RiskModel(ScriptedModel):
        def respond(self,phase,context,schema,timeout):
            if phase=='plan':
                # Reproduce the local model's inconsistent risk-plan category.
                return Plan(answer_type='descriptive',companies=['NVDA'],questions=['What risks could slow growth?'],evidence_requirements=['filing_explanations'])
            return super().respond(phase,context,schema,timeout)
    state=run_research('What are the biggest risks to NVIDIA growth?',RiskModel([tool(),done()]))
    assert state['plan']['evidence_requirements']==['filing_passages']
    assert state['report']['findings']
    assert state['report']['complete']


def test_live_risk_findings_survive_missing_financial_scope_and_years():
    from app.schemas import Evidence, Source, ToolResult
    from app.tools.registry import ToolRegistry
    class Provider:
        def execute(self,name,args):
            return ToolResult(status='ok',evidence=[Evidence(id='passage:risk',source_id='sec:test',ticker='NVDA',text='Export restrictions could prevent sales in affected markets and reduce demand for our products.',scope='unknown',section='risks')],sources=[Source(id='sec:test',title='Annual report risk factors',uri='https://www.sec.gov/test',synthetic=False)])
    class Model:
        def respond(self,phase,context,schema,timeout):
            if phase=='plan':
                return Plan(companies=['NVDA'],questions=['Growth risks?'],evidence_requirements=['filing_explanations'])
            if phase=='investigate':
                assert context['plan']['evidence_requirements']==['filing_passages']
                return tool()
            if phase=='assess':
                return EvidenceReview(findings=[Finding(id='claim_risk',text='Export restrictions could reduce product sales.',kind='risk',evidence_ids=['passage:risk'])],open_questions=[],sufficient=True)
            if phase=='verify':
                return Verification(coverage='sufficient',checks=[ClaimCheck(finding_id='claim_risk',status='supported',explanation='The excerpt discloses a prospective sales risk.')])
            return Synthesis(answer='',finding_ids=['claim_risk'],limitations=[],follow_up_questions=[])
    state=run_research('What are the biggest risks to NVIDIA growth?',Model(),registry=ToolRegistry(sec=Provider()))
    assert state['report']['complete']
    assert state['report']['findings'][0]['scope']=='unknown'
    assert state['report']['beginner_guide']['explanations']


def test_open_ended_research_plan_can_investigate_a_theme():
    class ThemeModel(ScriptedModel):
        def respond(self,phase,context,schema,timeout):
            if phase=='plan':
                return Plan(companies=['MSFT','NVDA','AAPL','AMD'],questions=['Which candidates disclose relevant exposure?'],evidence_requirements=['filing_passages'])
            return super().respond(phase,context,schema,timeout)
    state=run_research('Which companies could be exposed to an AI spending slowdown?',ThemeModel([tool(),done()]))
    assert len(state['plan']['companies'])==4
    assert state['tool_calls']
