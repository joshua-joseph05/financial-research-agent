from app.providers.filing_context import ContextualFiling
from app.agent.attribution import attribution_issue, explanation_gaps, render_findings


def parse(html):
    parser = ContextualFiling()
    parser.feed(html)
    return parser.passages()


HTML = '''
<h1>Item 7. Management discussion</h1>
<h2>SUMMARY RESULTS OF OPERATIONS</h2>
<b>Fiscal Year 2026 Compared with Fiscal Year 2025</b>
<p>Operating income increased because revenue grew faster than operating expenses across the consolidated business.</p>
<p>Microsoft Cloud gross margin percentage decreased due to infrastructure investments, partly offset by efficiencies.</p>
<h2>SEGMENT RESULTS OF OPERATIONS</h2>
<table><tr><td><b>Misleading table label</b></td><td>100</td></tr></table>
<p><b>Fiscal Year 2026 Compared with Fiscal Year 2025</b></p>
<p><i>Consumer Business</i></p>
<p>Gross margin increased due to product mix in this business, even though other businesses faced margin pressure.</p>
<p>PART II</p><p>Item 7</p>
<p>Operating expenses decreased because this business reduced distribution costs and streamlined advertising.</p>
<h2>OTHER INFORMATION</h2>
<p>A separate passage without an identified segment or comparative heading must not inherit earlier attribution.</p>
'''


def test_context_preserves_scope_comparison_and_page_breaks():
    passages = parse(HTML)
    company, cloud, segment, continuation, unknown = passages
    assert (company.scope, company.fiscal_years) == ('company', [2026, 2025])
    assert (cloud.scope, cloud.segment) == ('segment', 'Microsoft Cloud')
    assert (segment.scope, segment.segment, segment.fiscal_years) == ('segment', 'Consumer Business', [2026, 2025])
    assert continuation.segment == 'Consumer Business'
    assert (unknown.scope, unknown.fiscal_years) == ('unknown', [])
    assert all(p.segment != 'Misleading table label' for p in passages)


def test_context_does_not_infer_years_from_narrative_or_unknown_heading():
    rows = parse('<h2>SUMMARY RESULTS OF OPERATIONS</h2><p>Revenue increased during 2026 and operating expenses were stable, as management continued investing in the business.</p>')
    assert rows[0].fiscal_years == []


def test_comparison_heading_changes_do_not_relabel_prior_passages():
    html = HTML.split('<h2>SEGMENT')[0] + '<h3>Fiscal Year 2025 Compared with Fiscal Year 2024</h3><p>Operating income increased in the prior comparison period because the company expanded its customer base.</p>'
    rows = parse(html)
    assert rows[0].fiscal_years == [2026, 2025]
    assert rows[-1].fiscal_years == [2025, 2024]


def record(scope='company', segment=None, years=None):
    return {'id':'passage:one','ticker':'TEST','scope':scope,'segment':segment,'fiscal_years':years if years is not None else [2026,2025], 'text':'Evidence'}


def finding(scope='company', segment=None, years=None):
    return {'id':'claim','text':'Reported explanation.','evidence_ids':['passage:one'],'kind':'fact','scope':scope,'segment':segment,'fiscal_years':years if years is not None else [2026,2025],'explains_change':True}


def test_wrong_period_and_promoted_segment_are_rejected():
    assert 'scope' in attribution_issue(finding(), {'passage:one':record('segment','Consumer')})
    assert 'comparison years' in attribution_issue(finding(), {'passage:one':record(years=[2025,2024])})
    assert attribution_issue(finding(), {'passage:one':record()}) is None


def test_unknown_context_and_hypothetical_risk_cannot_explain_change():
    unknown = finding(scope='unknown', years=[])
    assert 'Unknown scope' in attribution_issue(unknown, {'passage:one':record('unknown',years=[])})
    risk = {**finding(), 'kind':'risk'}
    assert 'hypothetical risk' in attribution_issue(risk, {'passage:one':record()})


def test_mixed_comparison_claim_requires_splitting():
    claim = {**finding(), 'evidence_ids':['passage:one','passage:two']}
    assert attribution_issue(claim, {'passage:one':record(), 'passage:two':record(years=[2025,2024])})


def state_with(passages):
    return {'plan':{'evidence_requirements':['filing_explanations']}, 'observations': {
        'a':{'ticker':'TEST','value':'100','period_end':'2026-06-30'},
        'b':{'ticker':'TEST','value':'90','period_end':'2025-06-30'}, **passages}}


def test_completion_requires_correct_company_and_period_not_just_any_passage():
    state = state_with({'passage:one':record()})
    assert explanation_gaps(state, [])
    assert not explanation_gaps(state, [finding()])
    older = finding(years=[2025,2024])
    assert explanation_gaps(state_with({'passage:one':record(years=[2025,2024])}), [older])
    segment = finding('segment','Consumer')
    assert explanation_gaps(state_with({'passage:one':record('segment','Consumer')}), [segment])


def test_render_preserves_scope_year_and_interpretation_labels():
    claim = {**finding('segment','Consumer'), 'kind':'interpretation'}
    answer = render_findings([claim], {'passage:one':record('segment','Consumer')})
    assert 'Business area: Consumer' in answer
    assert 'FY 2026 vs FY 2025' in answer
    assert 'Interpretation' in answer


def run_attribution_case(scope='company', years=None, verification_gap=False, synthesis_gap=False):
    from app.agent.graph import run_research, Limits
    from app.schemas import Evidence, Source, ToolResult, Plan, Decision, ToolCall, Finding, EvidenceReview, Verification, ClaimCheck, Synthesis
    from app.tools.registry import ToolRegistry
    years = years or [2026, 2025]
    segment = 'Consumer' if scope == 'segment' else None
    passage = Evidence(id='passage:one', source_id='sec:test', ticker='TEST',
        text=f'Comparison years {years}: Operating income increased because revenue grew faster than costs.',
        scope=scope, segment=segment, fiscal_years=years)
    raw = [Evidence(id=f'raw:{year}', source_id='sec:test', ticker='TEST', text=f'Revenue for {year}: 100 USD',
        metric='revenue', value='100', unit='USD', period=f'{year}-06-30', period_start=f'{year-1}-07-01', period_end=f'{year}-06-30', period_type='annual') for year in (2026,2025)]
    change = Evidence(id='calc:change', source_id='sec:test', ticker='TEST', text='Revenue growth was 0.0000 percent.', metric='growth', operation='growth', value='0.0000', unit='percent', input_ids=['raw:2026', 'raw:2025'], period='2026-06-30')
    class Provider:
        def execute(self, name, args):
            return ToolResult(status='ok', evidence=raw+[passage, change], sources=[Source(id='sec:test', title='SEC filing', uri='https://www.sec.gov/test', synthetic=False)])
    class Model:
        calls = 0
        def respond(self, phase, context, schema, timeout):
            if phase == 'plan':
                return Plan(answer_type='historical_explanation', companies=['TEST'], questions=['Why did margins change?'], evidence_requirements=['filing_explanations'])
            if phase == 'investigate':
                self.calls += 1
                return Decision(action='tool',reason='Retrieve filing',tool=ToolCall(name='get_sec_filings',arguments={'ticker':'TEST'})) if self.calls == 1 else Decision(action='verify',reason='Verify')
            if phase == 'assess':
                return EvidenceReview(findings=[Finding(id='explanation', text='Operating income increased because revenue grew faster than costs.', evidence_ids=['passage:one'], scope=scope, segment=segment, fiscal_years=years, explains_change=True)], open_questions=[], sufficient=True)
            if phase == 'verify':
                return Verification(coverage='sufficient', checks=[ClaimCheck(finding_id='explanation',status='supported',explanation='Matches text')], unresolved_requirements=['Missing essential causal link'] if verification_gap else [])
            return Synthesis(answer='INVENTED summary attribution that was never verified.', finding_ids=['explanation'], limitations=[], follow_up_questions=[], unresolved_requirements=['Missing essential causal link'] if synthesis_gap else [])
    return run_research('Why did margins change?', Model(), Limits(max_verifications=1), registry=ToolRegistry(sec=Provider()))['report']


def test_live_render_cannot_introduce_unverified_summary_claims():
    report = run_attribution_case()
    assert report['complete']
    assert 'INVENTED' not in report['answer']
    assert 'Company-wide' in report['answer'] and 'FY 2026 vs FY 2025' in report['answer']


def test_segment_or_older_period_cannot_pass_company_explanation_requirement():
    assert not run_attribution_case(scope='segment')['complete']
    assert not run_attribution_case(years=[2025,2024])['complete']


def test_explicit_essential_gap_overrides_model_sufficient_verdict():
    assert not run_attribution_case(verification_gap=True)['complete']
    report = run_attribution_case(synthesis_gap=True)
    assert not report['complete']
    assert report['stop_reason'] == 'attribution_gap'


def test_calculated_dates_and_values_are_canonical_and_reproducible():
    from app.tools.registry import ToolRegistry
    from app.schemas import ToolCall
    from app.agent.attribution import calculation_findings
    from app.agent.graph import structural_check
    registry=ToolRegistry()
    raw=registry.execute(ToolCall(name='get_financials',arguments={'ticker':'MSFT'}),{})
    observations={e.id:e.model_dump() for e in raw.evidence}
    results=registry.execute(ToolCall(name='calculate_financial_metrics',arguments={'operation':'compare_operating_margins','evidence_ids':[
        'MSFT:2025:operating_income','MSFT:2025:revenue','MSFT:2024:operating_income','MSFT:2024:revenue']}),observations)
    observations.update({e.id:e.model_dump() for e in results.evidence})
    findings=calculation_findings(observations)
    assert len(findings)==3
    assert '5.0000 percentage points from 2024 to 2025' in findings[-1]['text']
    state={'observations':observations,'sources':{s.id:s.model_dump() for s in raw.sources+results.sources}}
    assert all(structural_check(f,state) is None for f in findings)


def test_numeric_records_cannot_assert_calculations_or_absence_of_filing_explanations():
    from app.agent.graph import structural_check
    from app.schemas import Evidence, Finding
    record=Evidence(id='n',source_id='s',ticker='TEST',text='Revenue: 100 USD',metric='revenue',value='100',unit='USD').model_dump()
    state={'observations':{'n':record},'sources':{'s':{}}}
    for text in ('Operating margin was calculated from revenue.', 'The filings do not contain explanations.'):
        claim=Finding(id='f',text=text,evidence_ids=['n']).model_dump()
        assert structural_check(claim,state)


def test_untried_filing_tools_are_not_mistaken_for_unavailable_sources():
    from app.agent.graph import run_research
    from app.schemas import Plan, ToolCall, Decision, EvidenceReview, Finding, Verification, ClaimCheck, Synthesis, Evidence, Source, ToolResult
    from app.tools.registry import ToolRegistry
    source=Source(id='s',title='SEC test',uri='https://www.sec.gov/test',synthetic=False)
    values=[Evidence(id=f'n:{year}',source_id='s',ticker='TEST',text=f'Revenue in {year} was 100 USD',value='100',metric='revenue',unit='USD',period_end=f'{year}-06-30') for year in (2025,2026)]
    passage=Evidence(id='passage:one',source_id='s',ticker='TEST',text='For 2026 compared with 2025, operating income increased because revenue grew faster than costs.',scope='company',fiscal_years=[2026,2025])
    class Provider:
        def execute(self,name,args):
            return ToolResult(status='ok',evidence=values if name=='get_financials' else [passage],sources=[source])
    class Model:
        decisions=iter([
            Decision(action='tool',reason='Get periods',tool=ToolCall(name='get_financials',arguments={'ticker':'TEST'})),
            Decision(action='verify',reason='Mistakenly think sources unavailable'),
            Decision(action='tool',reason='Retrieve untried source',tool=ToolCall(name='get_sec_filings',arguments={'ticker':'TEST'}))])
        verifications=0
        def respond(self,phase,context,schema,timeout):
            if phase=='plan':return Plan(companies=['TEST'],questions=['Explain the change'],evidence_requirements=['filing_explanations'])
            if phase=='investigate':return next(self.decisions)
            if phase=='assess':
                found='passage:one' in context['observations']
                return EvidenceReview(findings=[Finding(id='claim_driver',text='Operating income increased because revenue grew faster than costs.',evidence_ids=['passage:one'],scope='company',fiscal_years=[2026,2025],explains_change=True)] if found else [],open_questions=[] if found else ['Find explanations'],sufficient=found)
            if phase=='verify':
                assert any(t['name']=='get_sec_filings' for t in context['available_tools'])
                self.verifications+=1
                return Verification(coverage='limited_by_sources' if self.verifications==1 else 'sufficient',checks=[ClaimCheck(finding_id=f['id'],status='supported',explanation='Matches evidence') for f in context['findings']])
            return Synthesis(answer='',finding_ids=[f['id'] for f in context['findings']],limitations=[],follow_up_questions=[])
    state=run_research('Explain the change',Model(),registry=ToolRegistry(sec=Provider()))
    assert state['report']['complete']
    assert state['verification_count']==2
    assert [c['name'] for c in state['tool_calls']]==['get_financials','get_sec_filings']


def test_truncated_explanation_is_rejected():
    claim={**finding(),'text':'Expenses rose due to investment and higher'}
    assert 'Incomplete claim' in attribution_issue(claim,{'passage:one':record()})


def test_older_comparison_is_explicitly_rendered_as_background():
    older=finding(years=[2025,2024])
    older['explains_change']=False
    observations=state_with({'passage:one':record(years=[2025,2024])})['observations']
    assert 'Background only' in render_findings([older],observations)


def test_attribution_is_bound_from_citations_not_generated_by_model():
    from app.agent.attribution import bind_attribution
    claim={'id':'claim_x','text':'A reported driver.','evidence_ids':['passage:one'],'scope':None,'fiscal_years':[],'segment':None}
    bound=bind_attribution(claim,{'passage:one':record('segment','Consumer',[2025,2024])})
    assert bound['scope']=='segment' and bound['segment']=='Consumer'
    assert bound['fiscal_years']==[2025,2024]
    assert claim['scope'] is None


def test_unknown_comparison_context_can_support_prospective_risk():
    claim={**finding(scope='unknown',years=[]),'kind':'risk','explains_change':False,'text':'Export restrictions could limit product sales.'}
    assert attribution_issue(claim,{'passage:one':record(scope='unknown',years=[])}) is None


def test_removes_only_known_citation_suffix_not_claim_content():
    from app.agent.attribution import clean_citation_suffix
    claim={'text':'Export restrictions could limit sales. Evidence IDs: passage:one, passage:two','evidence_ids':['passage:one','passage:two']}
    assert clean_citation_suffix(claim)['text']=='Export restrictions could limit sales.'
    unknown={**claim,'text':'Claim. Evidence IDs: invented'}
    assert clean_citation_suffix(unknown)==unknown
