"""Offline evaluation tests exercise real graph paths; no LLM/provider calls."""
import json
import time
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import pytest
from app.evaluation.benchmark_data import load_cases
from app.evaluation.sources import BenchmarkRegistry,source_environment
from app.evaluation.recording import run_case
from app.evaluation.checks import deterministic_metrics,calculation_check,rate
from app.evaluation.judge import judge_run,judge_packet,assessment_metrics
from app.evaluation.benchmark import aggregate
from app.schemas import ToolCall,Plan,Decision,EvidenceReview,Finding,Verification,ClaimCheck,Synthesis
from app.assistant import Route


def case(id='sec_filings-01'):
    return next(c for c in load_cases() if c.id==id)

class ResearchModel:
    model='scripted-offline-research'
    def __init__(self,missing=False):self.missing=missing
    def respond(self,phase,context,schema,timeout):
        if phase=='assistant_route':return Route(workflow='research',reason='Company research')
        if phase=='plan':return Plan(companies=['MSFT'],questions=['What risks are disclosed?'],evidence_requirements=['filing_passages'])
        if phase=='investigate':
            calls=context.get('previous_calls',[])
            if not calls:return Decision(action='tool',reason='Understand the business',tool=ToolCall(name='get_sec_filings',arguments={'ticker':'MSFT','section':'business'}))
            if len(calls)==1:return Decision(action='tool',reason='Need risk disclosures',tool=ToolCall(name='get_sec_filings',arguments={'ticker':'MSFT','section':'risks'}))
            return Decision(action='verify',reason='Review available evidence')
        if phase=='assess':
            risks=[e for e in context['observations'].values() if e.get('section')=='risks']
            return EvidenceReview(findings=[Finding(id='risk',text='Infrastructure investment may increase depreciation and operating costs.',evidence_ids=[risks[0]['id']],kind='risk')] if risks else [],open_questions=[] if risks else ['Need risk disclosures'],sufficient=bool(risks))
        if phase=='verify':return Verification(coverage='limited_by_sources' if self.missing else 'sufficient',checks=[ClaimCheck(finding_id=f['id'],status='supported',explanation='Disclosed risk matches the source') for f in context['findings']],unresolved_requirements=['No available source'] if self.missing else [])
        if phase=='synthesize':return Synthesis(answer='',finding_ids=[f['id'] for f in context['findings']],limitations=[],follow_up_questions=[])
        raise AssertionError(phase)


def test_benchmark_has_ninety_labeled_cases_and_all_requested_categories():
    cases=load_cases();counts=Counter(c.category for c in cases)
    assert len(cases)==90 and len(counts)==9 and set(counts.values())=={10}
    assert all(c.criteria and c.expected_workflows for c in cases)
    assert {'unavailable_sources','missing_financials','ambiguous_company','no_recent_news','unsupported','stale_news','irrelevant_news'} <= {c.scenario for c in cases}


def test_real_graph_recognizes_gap_follows_up_and_stops():
    run=run_case(case(),ResearchModel(),budget=16)
    assert run['status']=='returned'
    calls=run['trace']['tool_calls']
    assert [c['arguments']['section'] for c in calls]==['business','risks']
    assert run['report']['complete']
    assert run['trace']['research_state']['stop_reason']=='evidence_sufficient'
    assert run['investigation_iterations']['research']>=2
    metrics=deterministic_metrics(case(),run)
    assert metrics['gap_decisions']>=1
    assert metrics['calculation_accuracy']['rate'] is None
    assert run['telemetry']['request_budget_used']>0
    assert run['trace']['research_state']['verification']['checks']


def test_missing_sources_do_not_create_findings():
    c=case().model_copy(update={'scenario':'unavailable_sources'})
    run=run_case(c,ResearchModel(missing=True),budget=16)
    assert not run['report']['complete']
    assert not run['report']['findings']
    assert any(c['status']=='error' for c in run['trace']['tool_calls'])
    assert deterministic_metrics(c,run)['tool_failures']>0


def test_clarification_records_route_without_tools():
    class Clarifier:
        def respond(self,*args):return Route(workflow='clarification',reason='Ambiguous company',clarification='Which Mercury company do you mean?')
    c=case('insufficient_evidence-01');run=run_case(c,Clarifier())
    assert run['workflow']=='clarification' and run['status']=='clarification'
    assert not run['trace']['tool_calls']
    assert deterministic_metrics(c,run)['routing_accuracy']['rate']==1


def test_outer_budget_preserves_failed_calls_and_limits_execution():
    run=run_case(case(),ResearchModel(),budget=1)
    assert run['telemetry']['request_budget_used']==1
    assert not run['report'] or not run['report'].get('complete')


def test_independent_calculation_oracle_detects_corruption_and_missing_inputs():
    registry=BenchmarkRegistry();raw=registry.execute(ToolCall(name='get_financials',arguments={'ticker':'MSFT'}),{})
    records={e.id:e.model_dump() for e in raw.evidence}
    ids=['fixture:MSFT:operating_income:2025','fixture:MSFT:revenue:2025']
    result=registry.execute(ToolCall(name='calculate_financial_metrics',arguments={'operation':'operating_margin','evidence_ids':ids}),records)
    record=result.evidence[0].model_dump()
    assert calculation_check(record,records)['expected_value']=='35.0000'
    assert calculation_check(record,records)['status']=='pass'
    assert calculation_check({**record,'value':'3500'},records)['status']=='fail'
    assert calculation_check(record,{})['status']=='fail'
    records[ids[1]]['period_start']='2025-02-01'
    assert calculation_check(record,records)['status']=='fail'


def test_frozen_news_and_history_cannot_hit_network(monkeypatch):
    import httpx
    def forbidden(*args,**kwargs):raise AssertionError('External network used')
    monkeypatch.setattr(httpx.Client,'send',forbidden)
    registry=BenchmarkRegistry()
    import app.ideas.tools as tools
    with source_environment(registry):
        news=tools.execute(registry,ToolCall(name='search_web',arguments={'ticker':'MSFT','query':'AI'}),{})
    assert news.status=='ok'
    for metric in ('revenue','net_income','operating_cash_flow','capital_expenditure','operating_margin'):
        result=registry.execute(ToolCall(name='get_financial_metric_history',arguments={'ticker':'MSFT','metric':metric}),{})
        assert result.status=='ok'
        assert all(e.source_id in {s.id for s in result.sources} for e in result.evidence)


def test_stale_and_missing_articles_are_explicit():
    for scenario in ('no_recent_news','stale_news'):
        registry=BenchmarkRegistry(scenario)
        catalog=registry.discover('MSFT','Microsoft','outlook',30,time.monotonic()+5)['candidates']
        if scenario=='no_recent_news':assert not catalog
        else:
            with pytest.raises(ValueError,match='Stale'):registry.read(next(iter(catalog.values())),30,time.monotonic()+5)

class Judge:
    model='scripted-offline-judge'
    def respond(self,phase,context,schema,timeout):
        if phase=='evaluation_task':return schema.model_validate({'criteria':[{'criterion_id':c['id'],'verdict':'pass','reason':'Matches the supplied criterion.'} for c in context['criteria']], 'tool_appropriateness':'appropriate','tool_reason':'The selected tools investigate the question.'})
        if phase=='evaluation_claims':return schema.model_validate({'checks':[{'claim_id':c['id'],'verdict':'supported' if c['cited_evidence'] else 'nonfactual','evidence_ids':list(c['cited_evidence'])[:1],'reason':'Reviewed against supplied evidence.'} for c in context['claims']]})
        raise AssertionError(phase)


def test_judge_has_separate_budget_and_does_not_receive_self_review():
    run=run_case(case(),ResearchModel(),budget=16)
    agent_requests=run['telemetry']['request_budget_used']
    packet=judge_packet(case(),run)
    assert 'verification' not in packet and 'complete' not in packet
    judged=judge_run(case(),run,Judge(),budget=12)
    assert judged['metrics']['task_completion']['rate']==1
    assert judged['telemetry']['request_budget_used']>0
    assert run['telemetry']['request_budget_used']==agent_requests
    assert judged['metrics']['claim_assessment_coverage']['rate']==1


def test_invalid_or_missing_judge_results_never_count_as_success():
    class BadJudge(Judge):
        def respond(self,phase,context,schema,timeout):
            if phase=='evaluation_claims':return schema.model_validate({'checks':[]})
            raise ValueError('Unavailable judge')
    run=run_case(case(),ResearchModel(),budget=16)
    judged=judge_run(case(),run,BadJudge(),budget=8)
    assert judged['metrics']['task_completion']['rate'] is None
    assert judged['metrics']['claim_assessment_coverage']['rate']==0
    assert judged['metrics']['unsupported_claim_rate']['rate'] is None
    assert judged['errors']


def test_manual_scores_reject_uncited_evidence():
    run=run_case(case(),ResearchModel(),budget=16);packet=judge_packet(case(),run)
    with pytest.raises(ValueError,match='uncited'):
        assessment_metrics(packet,{'claims':[{'claim_id':packet['claims'][0]['id'],'verdict':'supported','evidence_ids':['made-up'],'reason':'Invented evidence is invalid.'}]})


def test_aggregate_keeps_failures_and_quality_unassessed():
    run=run_case(case(),ResearchModel(),budget=16)
    run['deterministic']=deterministic_metrics(case(),run)
    result=aggregate([run],planned=90)
    assert result['recorded_runs']==1 and result['planned_runs']==90
    assert not result['llm_judged']
    assert result['deterministic']['calculation_accuracy']['rate'] is None


def test_all_authored_tool_labels_match_real_tools():
    from app.tools.registry import SPECS
    allowed=set(SPECS)|{'search_web','consult_sentiment','market_snapshot'}
    for item in load_cases():
        assert set(item.allowed_tools)<=allowed,item.id
        assert all(set(group)<=allowed for group in item.required_tool_groups),item.id

class SentimentModel:
    model='scripted-offline-sentiment'
    def __init__(self):self.steps=0
    def respond(self,phase,context,schema,timeout):
        if phase.endswith('_step'):
            self.steps+=1
            return schema.model_validate({'action':'read' if self.steps==1 else 'finish','article_ids':[a['id'] for a in context['candidates'][:2]]})
        if phase.endswith('_extract'):
            return schema.model_validate({'arguments':[{'article_id':a['id'],'kind':'analyst_opinion','stance':'bullish' if a['id'].endswith(':0') else 'bearish','point':a['body'].split('. ')[0]+'.','quote':a['body'].split('. ')[0]+'.','attribution':'Alex Reed' if a['id'].endswith(':0') else 'Jamie Park','importance':'high'} for a in context['articles']]})
        if phase.endswith('_synthesize'):
            ids=[a['id'] for a in context['arguments']]
            return schema.model_validate({'summary':{'text':'The fictional sample combines demand optimism with investment cost concerns.','argument_ids':ids},'verification_tasks':[{'text':'Check cash flow and capital expenditure before accepting the investment claims.','argument_ids':ids}]})
        if phase.endswith('_review'):
            return schema.model_validate({'checks':[{'argument_id':a['id'],'supported':True} for a in context['arguments']],'synthesis_supported':True})
        raise AssertionError(phase)


def test_separate_sentiment_evaluation_reads_sources_and_records_all_metrics():
    c=case('sentiment_news-01');run=run_case(c,SentimentModel(),budget=16,target='sentiment')
    assert run['report']['status']=='reviewed_sample'
    assert run['report']['overall_sentiment']=='mixed'
    assert len(run['trace']['articles'])==2
    assert run['investigation_iterations']['sentiment']==2
    assert any(d['phase']=='ideas_sentiment_extract' for d in run['trace']['model_decisions'])
    metrics=deterministic_metrics(c,run)
    assert metrics['sentiment_recency']['rate']==1
    assert metrics['sentiment_quote_integrity']['rate']==1
    assert metrics['sentiment_attribution_presence']['rate']==1
    assert metrics['citation_integrity']['rate']==1


def test_sentiment_without_recent_articles_does_not_invent_a_brief():
    c=case('sentiment_news-08');run=run_case(c,SentimentModel(),budget=16,target='sentiment')
    assert run['report']['status']=='insufficient_evidence'
    assert not run['report']['arguments']
    assert not run['report']['synthesis']
    assert deterministic_metrics(c,run)['sentiment_quote_integrity']['rate'] is None


def test_citation_integrity_catches_missing_sources_and_provenance_cycles():
    from app.evaluation.checks import provenance_valid
    records={'a':{'source_id':'s','input_ids':['b']},'b':{'source_id':'s','input_ids':['a']}}
    assert not provenance_valid('a',records,{'s':{}})
    assert not provenance_valid('x',records,{'s':{}})
    assert not provenance_valid('a',{'a':{'source_id':'s'}},{})


def test_summary_lower_is_better_for_unsupported_rate_and_keeps_partial_denominators():
    run=run_case(case(),ResearchModel(),budget=16)
    run['deterministic']=deterministic_metrics(case(),run)
    run['llm_judged']={'metrics':{'unsupported_claim_rate':rate(1,3),'claim_assessment_coverage':rate(3,7)}}
    summary=aggregate([run])
    assert summary['llm_judged']['unsupported_claim_rate']['rate']==1/3
    assert summary['llm_judged']['claim_assessment_coverage']['rate']==3/7


@pytest.mark.parametrize('ticker,expected_margin,expected_growth,expected_change',[
    ('MSFT','35.0000','20.0000','5.0000'),('NVDA','40.0000','50.0000','10.0000'),
    ('AAPL','28.8889','5.0000','-1.1111'),('AMD','13.3333','20.0000','3.3333')])
def test_frozen_calculations_match_independent_labeled_values(ticker,expected_margin,expected_growth,expected_change):
    registry=BenchmarkRegistry()
    records={e.id:e.model_dump() for e in registry.execute(ToolCall(name='get_financials',arguments={'ticker':ticker}),{}).evidence}
    ids=[f'fixture:{ticker}:{metric}:{year}' for year in (2025,2024) for metric in ('operating_income','revenue')]
    result=registry.execute(ToolCall(name='calculate_financial_metrics',arguments={'operation':'compare_operating_margins','evidence_ids':ids}),records)
    assert result.status=='ok'
    records.update({e.id:e.model_dump() for e in result.evidence})
    assert result.evidence[0].value==expected_margin
    assert result.evidence[-1].value==expected_change
    assert all(calculation_check(e.model_dump(),records)['status']=='pass' for e in result.evidence)
    growth=registry.execute(ToolCall(name='calculate_financial_metrics',arguments={'operation':'growth','evidence_ids':[ids[1],ids[3]]}),records)
    assert growth.evidence[0].value==expected_growth
    assert calculation_check(growth.evidence[0].model_dump(),records)['status']=='pass'


def test_judge_rejects_duplicate_claim_ids_and_incomplete_sentiment_checks():
    run=run_case(case(),ResearchModel(),budget=16);packet=judge_packet(case(),run)
    item={'claim_id':packet['claims'][0]['id'],'verdict':'nonfactual','evidence_ids':[],'reason':'Procedural statement only.'}
    with pytest.raises(ValueError,match='Duplicate'):
        assessment_metrics(packet,{'claims':[item,item]})
    c=case('sentiment_news-01');run=run_case(c,SentimentModel(),budget=16,target='sentiment')
    with pytest.raises(ValueError,match='exactly once'):
        assessment_metrics(judge_packet(c,run),{'sentiment':{'sources':[],'arguments':[]}})


def test_cli_preview_and_request_guard_make_no_model_calls(tmp_path,monkeypatch,capsys):
    import app.evaluation.benchmark as benchmark
    def forbidden(*args,**kwargs):raise AssertionError('No model should be created')
    monkeypatch.setattr(benchmark,'create_model',forbidden)
    monkeypatch.setattr('sys.argv',['benchmark','--case','all','--judge','--dry-run','--output',str(tmp_path/'unused')])
    benchmark.main()
    assert '4320' in capsys.readouterr().out
    assert not (tmp_path/'unused').exists()
    monkeypatch.setattr('sys.argv',['benchmark','--case','all','--judge','--output',str(tmp_path/'unused')])
    with pytest.raises(SystemExit):benchmark.main()
    assert not (tmp_path/'unused').exists()


def test_full_cli_artifacts_and_manual_review_import(tmp_path,monkeypatch):
    import app.evaluation.benchmark as benchmark
    import app.evaluation.review as review
    output=tmp_path/'run'
    monkeypatch.setattr(benchmark,'create_model',lambda *args,**kwargs:Judge() if kwargs.get('system_prompt') else ResearchModel())
    monkeypatch.setattr('sys.argv',['benchmark','--case','sec_filings-01','--judge','--output',str(output)])
    benchmark.main()
    index=json.loads((output/'index.json').read_text())
    assert len(index)==1
    artifact=output/(index[0]['label']+'.json');run=json.loads(artifact.read_text())
    assert run['workflow']=='research'
    assert run['llm_judged']['metrics']['task_completion']['rate']==1
    packet_path=output/(index[0]['label']+'.review.json');manual=json.loads(packet_path.read_text())
    manual.update(reviewer='Offline test reviewer',task=run['llm_judged']['task'],claims=run['llm_judged']['claims'])
    packet_path.write_text(json.dumps(manual))
    monkeypatch.setattr('sys.argv',['review',str(output),'--import-manual']);review.main()
    updated=json.loads(artifact.read_text())
    assert updated['manual']['method']=='manual'
    assert updated['manual']['metrics']['task_completion']['rate']==1
    assert 'llm_judged' in updated
    assert (output/'summary.md').exists()


def test_recent_future_and_invalid_dates_are_not_silently_accepted():
    c=case('sentiment_news-01');run=run_case(c,SentimentModel(),budget=16,target='sentiment')
    sample=run['trace']['sentiment_results'][0]
    sample['sources'][0]['published']='2026-09-24'
    sample['sources'][1]['published']='not-a-date'
    assert deterministic_metrics(c,run)['sentiment_recency']['rate']==0


def test_attempted_tool_metrics_do_not_credit_rejected_proposals():
    c=case();run=run_case(c,ResearchModel(),budget=16)
    run['trace']['tool_calls']=[]
    run['trace']['research_state']=None
    run['report']={}
    run['trace']['model_decisions']=[{'phase':'investigate','output':{'action':'tool','tool':{'name':'get_sec_filings','arguments':{}}}}]
    measured=deterministic_metrics(c,run)
    assert measured['tool_selection_label_precision']['rate']==0
    assert measured['required_tool_group_coverage']['rate']==0


def test_fixture_scope_filter_exposes_missing_segment_evidence():
    registry=BenchmarkRegistry()
    result=registry.execute(ToolCall(name='get_sec_filings',arguments={'ticker':'MSFT','section':'risks','scope':'segment'}),{})
    assert result.status=='no_data'
    assert not result.evidence
