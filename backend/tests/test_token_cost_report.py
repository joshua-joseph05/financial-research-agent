import runpy
from pathlib import Path
import pytest

module=runpy.run_path(str(Path(__file__).parents[2]/'scripts'/'report-token-cost.py'))


def inputs():
    runs=[{'case_id':case,'execution_profile':profile,'report':{'answer':case},'telemetry':{'tokens':{'prompt_tokens':90,'completion_tokens':10}}} for profile in ('standard','efficient') for case in ('a','b')]
    review={'runs':[{'case_id':r['case_id'],'profile':r['execution_profile'],'answer_sha256':module['answer_hash'](r),'complete':r['case_id']=='a' or r['execution_profile']=='efficient','supported':True} for r in runs]}
    return runs,review


def test_failed_attempt_tokens_count_toward_cost_per_success():
    runs,review=inputs();result=module['calculate'](runs,review)
    assert result['profiles']['standard']['tokens_per_success_including_failures']==200
    assert result['profiles']['efficient']['tokens_per_success_including_failures']==100
    assert result['token_cost_per_success_reduction_percent']==50


def test_missing_usage_is_unknown_not_free():
    runs,review=inputs();runs[-1]['telemetry']['tokens']={}
    result=module['calculate'](runs,review)
    assert result['profiles']['efficient']['total_tokens'] is None
    assert result['token_cost_per_success_reduction_percent'] is None


def test_unreviewed_or_changed_answers_cannot_receive_cost_success_score():
    runs,review=inputs();review['runs'][0]['complete']=None
    with pytest.raises(ValueError):module['calculate'](runs,review)
    runs,review=inputs();runs[0]['report']['answer']='changed'
    with pytest.raises(ValueError):module['calculate'](runs,review)
