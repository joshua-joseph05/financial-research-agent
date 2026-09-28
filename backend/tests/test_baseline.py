"""Offline checks of the comparison contract, with actual agent traces."""
from copy import deepcopy
import json
import pytest
from test_benchmark import case, ResearchModel, Judge
from app.evaluation.recording import run_case
from app.evaluation.baseline import run_baseline, evidence_bundle, answer_calculations
from app.evaluation.baseline_compare import compare_pair
from app.evaluation.baseline_report import comparison_summary, outcome, measures
from app.evaluation.judge import manual_template

class BaselineModel:
    model=ResearchModel.model
    def __init__(self):self.contexts=[]
    def respond(self,phase,context,schema,timeout):
        self.contexts.append((phase,context))
        assert phase=='baseline_answer'
        evidence=context['evidence']
        return schema.model_validate({'sections':[{'text':'Infrastructure investment may increase costs.','evidence_ids':[evidence[0]['id']]}]})

@pytest.fixture
def agent():
    result=run_case(case(),ResearchModel(),budget=16)
    result['label']='001-sec_filings-01-enabled-r1'
    return result

def test_baseline_one_call_no_tools_and_same_model(agent):
    model=BaselineModel(); result=run_baseline(agent,model)
    assert result['status']=='returned'
    assert len(model.contexts)==1 and result['telemetry']['model_calls']==1
    assert result['trace']['tool_calls']==[]
    assert result['investigation_iterations']=={'research':0,'investment':0,'sentiment':0}
    model.model='different'
    with pytest.raises(ValueError,match='exact agent model'):run_baseline(agent,model)

def test_bundle_does_not_leak_agent_answers_or_judgments(agent):
    agent['report']['answer']='SECRET ANSWER'
    agent['report']['findings'][0]['text']='SECRET FINDING'
    agent['llm_judged']={'secret':'SECRET JUDGMENT'}
    bundle,digest=evidence_bundle(agent)
    encoded=json.dumps(bundle)
    assert 'SECRET' not in encoded
    assert len(bundle['evidence'])>=2
    assert digest==evidence_bundle(deepcopy(agent))[1]
    assert set(bundle)=={'question','as_of','data_mode','evidence','sources','articles','source_limitations'}

def test_baseline_failure_is_retained_not_perfect(agent):
    class Broken(BaselineModel):
        def respond(self,*args):raise TimeoutError('failure')
    result=run_baseline(agent,Broken())
    assert result['status']=='error' and result['errors']
    assert result['telemetry']['model_calls']==1
    assert answer_calculations(result)['metric']['rate'] is None
    assert result['trace']['provided_evidence']

def test_fresh_identical_answer_only_judges_and_resume(agent):
    contexts=[]
    class Audit(Judge):
        def respond(self,phase,context,schema,timeout):
            contexts.append((phase,deepcopy(context)))
            if phase=='evaluation_task':
                assert context['tools']==context['decisions']==[]
                assert 'Assess tools for this question' not in context['instruction']
                assert 'system' not in context
            return super().respond(phase,context,schema,timeout)
    agent['llm_judged']={'metrics':{'task_completion':{'rate':0}}}
    model=BaselineModel()
    pair=compare_pair(case(),agent,model,Audit)
    task_contexts=[c for p,c in contexts if p=='evaluation_task']
    assert len(task_contexts)==2
    assert task_contexts[0]['criteria']==task_contexts[1]['criteria']
    assert task_contexts[0]['available_evidence']==task_contexts[1]['available_evidence']
    assert pair['judgments']['agent']['metrics']['task_completion']['rate']==1
    count=len(contexts)
    compare_pair(case(),agent,model,Audit,cached=pair)
    assert len(contexts)==count and len(model.contexts)==1
    assert manual_template(case(),agent)['rubric_version']=='1.0'

def test_reports_keep_missing_categories_and_partial_judging(agent):
    pair=compare_pair(case(),agent,BaselineModel(),Judge)
    pair['judgments']['baseline']['metrics']['claim_assessment_coverage']['rate']=0.5
    assert measures(pair,'baseline')['citation_correctness'] is None
    summary=comparison_summary([pair],{'sec_filings':10,'education':10})
    assert summary['recorded_pairs']==1 and summary['planned_pairs']==20
    assert summary['categories']['education']['recorded']==0
    assert summary['metrics']['citation_correctness']['paired_cases']==0
    pair['judgments']['agent']['metrics']['task_completion']['rate']=None
    assert outcome(pair)[0]=='unassessed'

@pytest.mark.parametrize('a,b,expected',[(1,0,'agent_improves'),(0,1,'agent_worse'),(1,1,'no_measured_quality_gain')])
def test_report_does_not_prefer_agent(agent,a,b,expected):
    pair=compare_pair(case(),agent,BaselineModel(),Judge)
    for system,value in [('agent',a),('baseline',b)]:
        pair['judgments'][system]['metrics']={'task_completion':{'rate':value}}
    assert outcome(pair)[0]==expected

def test_calculations_only_count_used_outputs_and_detect_corruption(agent):
    from app.evaluation.sources import BenchmarkRegistry
    from app.schemas import ToolCall
    registry=BenchmarkRegistry()
    raw=registry.execute(ToolCall(name='get_financials',arguments={'ticker':'MSFT'}),{})
    records={e.id:e.model_dump() for e in raw.evidence}
    calculated=registry.execute(ToolCall(name='calculate_financial_metrics',arguments={'operation':'operating_margin','evidence_ids':['fixture:MSFT:operating_income:2025','fixture:MSFT:revenue:2025']}),records)
    result=run_baseline(agent,BaselineModel())
    result['report']['evidence']+=list(records.values())+[e.model_dump() for e in calculated.evidence]
    assert answer_calculations(result)['metric']['rate'] is None
    calc=result['report']['evidence'][-1]
    result['report']['answer_sections'][0]['evidence_ids']=[calc['id']]
    assert answer_calculations(result)['metric']['rate']==1
    calc['value']='999'
    assert answer_calculations(result)['metric']['rate']==0

def test_source_lock_prevents_concurrent_inference(tmp_path):
    import fcntl
    from app.evaluation.baseline_compare import source_lock
    with (tmp_path/'.run.lock').open('a') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(ValueError,match='Source evaluation is running'):
            with source_lock(tmp_path):pytest.fail('Entered active source lock')
    with source_lock(tmp_path):pass

def test_sentiment_interpretations_not_used_as_their_own_evidence(agent):
    from app.evaluation.judge import judge_run
    agent['trace']['articles']={'article':{'id':'article','body':'Revenue increased.','url':'https://example.org','title':'Earnings'}}
    agent['trace']['sentiment_results']=[{'arguments':[{'id':'argument','article_id':'article','point':'Unsupported opinion','quote':'Revenue increased.'}]}]
    bundle,_=evidence_bundle(agent)
    assert 'argument' not in {e['id'] for e in bundle['evidence']}
    assert 'article' in {e['id'] for e in bundle['evidence']}
    class Audit(Judge):
        def respond(self,phase,context,schema,timeout):
            assert phase!='evaluation_sentiment'
            if phase=='evaluation_claims':
                assert all('argument' not in c['cited_evidence'] for c in context['claims'])
            return super().respond(phase,context,schema,timeout)
    judge_run(case(),agent,Audit(),answer_only=True,shared_evidence=bundle['evidence'])

def test_cli_writes_real_matched_reports_and_resumes_without_model_calls(agent,tmp_path,monkeypatch):
    import sys
    import app.evaluation.baseline_compare as cli
    from app.evaluation.baseline import SYSTEM
    source=tmp_path/'agent';source.mkdir();output=tmp_path/'comparison'
    agent['model']['class']='BaselineModel'
    (source/'manifest.json').write_text(json.dumps({'planned_runs':1,'cases':[case().model_dump()],
        'provider':'ollama','options':{'repeats':1,'sentiment':'enabled'}}))
    (source/'index.json').write_text(json.dumps([{'label':agent['label']}]))
    (source/(agent['label']+'.json')).write_text(json.dumps(agent))
    calls=[]
    def factory(model=None,system_prompt=None):
        calls.append(system_prompt)
        return BaselineModel() if system_prompt==SYSTEM else Judge()
    monkeypatch.setattr(cli,'create_model',factory)
    argv=['baseline_compare','--agent-directory',str(source),'--output',str(output)]
    monkeypatch.setattr(sys,'argv',argv);cli.main()
    report=json.loads((output/'comparison.json').read_text())
    assert report['recorded_pairs']==report['planned_pairs']==1
    assert report['categories']['sec_filings']['recorded']==1
    assert set(report['metrics'])=={'task_completion','citation_correctness','calculation_accuracy','unsupported_claim_rate','latency_seconds','model_calls','model_requests','tool_calls'}
    assert report['metrics']['model_calls']['baseline_mean']==1
    assert report['metrics']['tool_calls']['baseline_mean']==0
    assert (output/'comparison.md').is_file()
    assert json.loads((output/'manifest.json').read_text())['state']=='complete'
    # Constructing the baseline provider is harmless; responding again is not.
    class NoCall(BaselineModel):
        def respond(self,*args):raise AssertionError('Cached answer must not run again')
    def resumed(model=None,system_prompt=None):
        assert system_prompt==SYSTEM
        instance=BaselineModel()
        instance.respond=NoCall().respond
        return instance
    monkeypatch.setattr(cli,'create_model',resumed)
    monkeypatch.setattr(sys,'argv',argv+['--resume']);cli.main()
    assert json.loads((output/'comparison.json').read_text())==report

def test_comparison_claim_batches_fit_local_output_budget(agent):
    from app.evaluation.judge import judge_run
    agent['report']={'answer_sections':[{'text':f'Explanation {i}','evidence_ids':[]} for i in range(10)]}
    sizes=[]
    class Audit(Judge):
        def respond(self,phase,context,schema,timeout):
            if phase=='evaluation_claims':sizes.append(len(context['claims']))
            return super().respond(phase,context,schema,timeout)
    result=judge_run(case(),agent,Audit(),answer_only=True)
    assert sizes==[3,3,3,1]
    assert result['metrics']['claim_assessment_coverage']['rate']==1

def test_small_benchmark_has_distinct_prompts_and_balanced_categories():
    from pathlib import Path
    from collections import Counter
    from app.evaluation.benchmark_data import load_cases
    ids=json.loads((Path(__file__).parents[1]/'app/evaluation/benchmark18.json').read_text())['case_ids']
    cases={c.id:c for c in load_cases()}
    assert len(ids)==len(set(ids))==18
    selected=[cases[key] for key in ids]
    assert len({c.question.casefold().strip() for c in selected})==18
    assert len(Counter(c.category for c in selected))==9
    assert set(Counter(c.category for c in selected).values())=={2}


def test_answers_only_skips_legacy_judges_and_preserves_baseline_on_resume(agent):
    def forbidden():
        raise AssertionError('Legacy judge must not run')
    model=BaselineModel()
    pair=compare_pair(case(),agent,model,forbidden,assess=False)
    assert len(model.contexts)==1
    assert pair['judgments']=={}
    assert 'calculations' in pair
    assert comparison_summary([pair],{case().category:1})['metrics']['task_completion']['paired_cases']==0
    compare_pair(case(),agent,model,forbidden,cached=pair,assess=False)
    assert len(model.contexts)==1
