from app.agent.coverage import coverage_status, coverage_gaps
from app.agent.graph import EfficientPlan
from app.providers.llm import response_schema


def test_other_company_and_wrong_section_do_not_fill_missing_coverage():
    plan={'coverage_targets':[{'ticker':'MSFT','needs':['business','risks']},{'ticker':'NVDA','needs':['business','risks','calculated_metrics']}]}
    obs={'m':{'ticker':'MSFT','section':'risks'},'n':{'ticker':'NVDA','section':'business'},'c':{'ticker':'MSFT','operation':'operating_margin'}}
    assert coverage_status(plan,obs)==[
        {'ticker':'MSFT','retrieved':['risks'],'missing':['business']},
        {'ticker':'NVDA','retrieved':['business'],'missing':['risks','calculated_metrics']}]
    assert len(coverage_gaps(plan,obs))==2


def test_no_forced_coverage_on_other_questions():
    assert coverage_gaps({}, {})==[]
    assert coverage_status({'coverage_targets':[]},{})==[]


def test_financial_coverage_needs_both_raw_measures():
    plan={'coverage_targets':[{'ticker':'X','needs':['financial_values']}]}
    obs={'r':{'ticker':'X','metric':'revenue','value':'10'}}
    assert coverage_gaps(plan,obs)
    obs['i']={'ticker':'X','metric':'operating_income','value':'2'}
    assert not coverage_gaps(plan,obs)


def test_local_schema_requires_explicit_coverage_decision():
    schema=response_schema('plan',{'available_tools':[]},EfficientPlan)
    assert 'coverage_targets' in schema['required']


def test_empty_markers_do_not_erase_real_requirements():
    from app.agent.coverage import meaningful_requirements
    assert meaningful_requirements(['None',' N/A ','null','Not applicable.','None of the requested income figures were retrieved.','Missing NVIDIA risks'])==['None of the requested income figures were retrieved.','Missing NVIDIA risks']


def test_planning_checklist_does_not_claim_research_is_completed():
    from app.ideas.research_checks import checklist_outline, research_checks
    outline=checklist_outline()
    assert 'not completed' in outline['status']
    assert len(outline['checks'])==5
    assert [r['title'] for r in outline['checks']]==[r['title'] for r in research_checks('X',{}, {},[],[])]
    assert all(set(row)=={'title','question'} for row in outline['checks'])


def annual(metric,year,value='10',**changes):
    return {'ticker':'AMD','metric':metric,'value':value,'period_end':f'{year}-12-31','period_type':'annual','scope':'company','unit':'USD',**changes}


def declared(metrics,periods=2):
    return {'coverage_targets':[{'ticker':'AMD','needs':['financial_values'],'financial_metrics':metrics,'minimum_periods':periods}]}


def test_profit_growth_does_not_require_unrequested_revenue():
    plan=declared(['operating_income'])
    obs={'old':annual('operating_income',2024,'5'),'new':annual('operating_income',2025,'8')}
    assert not coverage_gaps(plan,obs)
    assert coverage_gaps(declared(['revenue','operating_income']),obs)


def test_cash_flow_requires_its_own_two_periods_not_duplicate_records():
    plan=declared(['operating_cash_flow'])
    old=annual('operating_cash_flow',2024)
    assert coverage_gaps(plan,{'a':old,'duplicate':old.copy(),'unrelated':annual('revenue',2025)})
    assert not coverage_gaps(plan,{'a':old,'b':annual('operating_cash_flow',2025)})


def test_multiple_metrics_must_share_comparable_periods():
    plan=declared(['revenue','operating_income'])
    obs={'r1':annual('revenue',2023),'r2':annual('revenue',2024),'i1':annual('operating_income',2024),'i2':annual('operating_income',2025)}
    assert coverage_gaps(plan,obs)
    obs['r3']=annual('revenue',2025)
    assert not coverage_gaps(plan,obs)


def test_incompatible_or_invalid_records_cannot_complete_new_coverage():
    plan=declared(['operating_cash_flow'])
    good=annual('operating_cash_flow',2024)
    for changes in [{'unit':'EUR'},{'scope':'segment'},{'period_type':'quarterly'},{'operation':'growth'}, {'value':'NaN'},{'value':None},{'period_end':'unknown'}, {'ticker':'MSFT'}]:
        assert coverage_gaps(plan,{'old':good,'new':annual('operating_cash_flow',2025,**changes)})
    assert coverage_gaps(declared([]),{'old':good})


def test_planning_schema_requires_metric_and_period_declarations():
    schema=response_schema('plan',{'available_tools':[]},EfficientPlan)
    assert {'financial_metrics','minimum_periods'}<=set(schema['$defs']['CoverageTarget']['required'])


def test_calculation_options_focus_on_missing_company_without_executing():
    from app.agent.coverage import calculation_gap_options
    from app.evaluation.sources import BenchmarkRegistry
    from app.schemas import ToolCall
    registry=BenchmarkRegistry();obs={}
    for ticker in ('MSFT','AAPL'):
        result=registry.execute(ToolCall(name='get_financial_metric_history',arguments={'ticker':ticker,'metric':'operating_cash_flow','years':2}),obs)
        obs.update({e.id:e.model_dump() for e in result.evidence})
    call=ToolCall(name='calculate_financial_metrics',arguments={'operation':'growth','evidence_ids':['fixture:MSFT:operating_cash_flow:2025','fixture:MSFT:operating_cash_flow:2024']})
    computed=registry.execute(call,obs);obs.update({e.id:e.model_dump() for e in computed.evidence})
    plan={'coverage_targets':[{'ticker':ticker,'needs':['calculated_metrics']} for ticker in ('MSFT','AAPL')]}
    count=len(registry.calls)
    options=calculation_gap_options(plan,obs,registry.descriptions(obs,registry.calls))
    assert len(registry.calls)==count
    assert options==[{'ticker':'AAPL','tool':{'name':'calculate_financial_metrics','arguments':{'operation':'growth','evidence_ids':['fixture:AAPL:operating_cash_flow:2025','fixture:AAPL:operating_cash_flow:2024']}}}]
    result=registry.execute(ToolCall.model_validate(options[0]['tool']),obs)
    obs.update({e.id:e.model_dump() for e in result.evidence})
    assert calculation_gap_options(plan,obs,registry.descriptions(obs,registry.calls))==[]
