import json
from pathlib import Path
from app.evaluation.benchmark_data import load_cases, CATEGORIES
from app.evaluation.efficiency import summarize, answer_hash


def test_broad_pilot_splits_are_disjoint_and_cover_every_category():
    suite=json.loads((Path(__file__).parents[1]/'app/evaluation/efficiency_broad.json').read_text())
    cases={c.id:c for c in load_cases()}
    assert not set(suite['development']) & set(suite['validation'])
    for split in ('development','validation'):
        assert len(suite[split])==len(CATEGORIES)
        assert {cases[key].category for key in suite[split]}==set(CATEGORIES)


def test_aggregate_gain_cannot_hide_category_completion_regression(tmp_path):
    runs=[];review={'reviewer':'controlled test','runs':[]}
    for category in ('financial_data','investment'):
        for profile in ('standard','efficient'):
            run={'case_id':category,'category':category,'execution_profile':profile,'report':{'answer':'fixture'},'status':'returned','latency_seconds':2 if profile=='standard' else 1,'telemetry':{'model_calls':4 if profile=='standard' else 3}}
            runs.append(run)
            complete=(category=='financial_data') == (profile=='standard')
            review['runs'].append({'case_id':category,'profile':profile,'answer_sha256':answer_hash(run),'complete':complete,'supported':True})
    path=tmp_path/'review.json';path.write_text(json.dumps(review))
    summarize(tmp_path,runs,path,development=set(),validation={'financial_data','investment'})
    gate=json.loads((tmp_path/'summary.json').read_text())['gate']
    assert gate['measured_efficiency_gain']
    assert not gate['category_quality_nonregression']
    assert gate['status']=='do_not_promote'


def token_experiment(tmp_path, standard_tokens, efficient_tokens, validation=None):
    runs=[]; review={'reviewer':'controlled test','runs':[]}
    for profile,tokens in [('standard',standard_tokens),('efficient',efficient_tokens)]:
        for index,value in enumerate(tokens):
            case_id=f'case-{index}'
            run={'case_id':case_id,'category':'education','execution_profile':profile,
                 'report':{'answer':'fixture'},'status':'returned',
                 'latency_seconds':2 if profile=='standard' else 1,
                 'telemetry':{'model_calls':4 if profile=='standard' else 3,'tokens':{'total_tokens':value}}}
            runs.append(run)
            review['runs'].append({'case_id':case_id,'profile':profile,'answer_sha256':answer_hash(run),
                                  'complete':index==0,'supported':True})
    path=tmp_path/'review.json';path.write_text(json.dumps(review))
    ids={r['case_id'] for r in runs}
    summarize(tmp_path,runs,path,development=ids if validation==set() else set(),validation=ids if validation is None else validation)
    return json.loads((tmp_path/'summary.json').read_text())


def test_faster_answers_with_more_tokens_cannot_pass_gate(tmp_path):
    result=token_experiment(tmp_path,[100],[150])
    assert result['gate']['measured_efficiency_gain']
    assert result['gate']['quality_nonregression']
    assert not result['gate']['token_cost_nonregression']
    assert result['gate']['status']=='do_not_promote'


def test_tokens_on_unsuccessful_answers_count_toward_cost(tmp_path):
    result=token_experiment(tmp_path,[100,300],[80,200])
    profile=result['metrics']['validation']['profiles']['efficient']
    assert profile['reviewed_supported_completions']==1
    assert profile['tokens_per_supported_completion']==280
    assert result['gate']['token_cost_nonregression']


def test_missing_usage_cannot_be_treated_as_free(tmp_path):
    result=token_experiment(tmp_path,[100],[None])
    assert result['metrics']['validation']['profiles']['efficient']['total_tokens'] is None
    assert not result['gate']['token_usage_complete']
    assert result['gate']['status']=='do_not_promote'


def test_empty_validation_does_not_crash_or_promote(tmp_path):
    result=token_experiment(tmp_path,[100],[80],validation=set())
    assert result['gate']['status']=='awaiting_validation_review'


def test_quality_and_efficiency_gains_with_known_lower_tokens_pass_small_sample_gate(tmp_path):
    result=token_experiment(tmp_path,[100],[80])
    assert result['gate']['status']=='promising_small_sample'


def test_known_usage_with_zero_baseline_success_is_not_missing_telemetry(tmp_path):
    runs=[];items=[]
    for profile in ('standard','efficient'):
        run={'case_id':'x','category':'education','execution_profile':profile,'report':{'answer':'fixture'},'status':'returned',
             'latency_seconds':2 if profile=='standard' else 1,'telemetry':{'model_calls':4 if profile=='standard' else 3,'tokens':{'total_tokens':100 if profile=='standard' else 80}}}
        runs.append(run)
        items.append({'case_id':'x','profile':profile,'answer_sha256':answer_hash(run),'complete':profile=='efficient','supported':True})
    path=tmp_path/'review.json';path.write_text(json.dumps({'runs':items}))
    summarize(tmp_path,runs,path,development=set(),validation={'x'})
    result=json.loads((tmp_path/'summary.json').read_text())
    assert result['gate']['token_usage_complete']
    assert not result['gate']['success_cost_comparable']
    assert not result['gate']['token_cost_nonregression']
    assert result['metrics']['validation']['profiles']['standard']['tokens_per_supported_completion'] is None
    assert result['gate']['status']=='do_not_promote'
