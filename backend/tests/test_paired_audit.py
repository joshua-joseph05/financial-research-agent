from copy import deepcopy
import pytest
from app.evaluation.paired_audit import audit,review_packet,import_scores
from app.evaluation.efficiency import answer_hash


def fixture():
    manifest={'settings':{'cases':[{'id':'one','question':'one'},{'id':'two','question':'two'}],'rubric':{'one':'Answer one with sources','two':'Answer two with sources'}}}
    runs=[];review={'reviewer':'Test rubric reviewer','runs':[]}
    for case in ('one','two'):
        for profile in ('standard','efficient'):
            run={'case_id':case,'execution_profile':profile,'category':'education','question':case,
                 'report':{'answer':case+profile,'telemetry':{'model_calls':99},'sources':[{'id':'s'}]},
                 'telemetry':{'model_calls':5 if profile=='standard' else 3,'tokens':{'total_tokens':100 if profile=='standard' else 60}},'latency_seconds':10 if profile=='standard' else 5}
            runs.append(run)
            review['runs'].append({'case_id':case,'profile':profile,'answer_sha256':answer_hash(run),'complete':case=='one','supported':True,'notes':'audited'})
    return manifest,runs,review


def test_failures_are_not_presented_as_successful_task_speed():
    m,r,v=fixture();result=audit(r,v,m)
    assert result['questions']==2 and result['successful_in_both']['questions']==1
    assert result['all_attempts']['tokens']['standard']==200
    assert result['successful_in_both']['metrics']['tokens']['standard']==100
    assert result['cases'][1]['candidate_failure']


@pytest.mark.parametrize('problem',['missing_pair','duplicate','unknown','stale_review','unreviewed','missing_review'])
def test_invalid_experiments_cannot_produce_clean_audit(problem):
    m,r,v=fixture()
    if problem=='missing_pair':r.pop()
    if problem=='duplicate':r.append(r[0])
    if problem=='unknown':r[0]['case_id']='unknown'
    if problem=='stale_review':r[0]['report']['answer']='changed'
    if problem=='unreviewed':v['runs'][0]['complete']=None
    if problem=='missing_review':v['runs'].pop()
    with pytest.raises(ValueError):audit(r,v,m)


def test_no_matched_success_and_missing_usage_remain_unknown():
    m,r,v=fixture()
    for item in v['runs']:item['complete']=False
    r[0]['telemetry']['tokens']['total_tokens']=None
    result=audit(r,v,m)
    assert result['all_attempts']['tokens']['standard'] is None
    assert result['all_attempts']['tokens']['reduction_percent'] is None
    assert result['successful_in_both']['questions']==0
    assert result['successful_in_both']['metrics']['seconds']['reduction_percent'] is None


def test_version_hidden_packet_preserves_evidence_and_imports_bound_scores():
    m,r,v=fixture();original=deepcopy(r)
    packet,mapping,scores=review_packet(r,m)
    assert r==original
    for case in packet['cases']:
        for answer in case['answers']:
            assert 'telemetry' not in answer['report'] and answer['report']['sources']
            assert 'profile' not in answer
    scores['reviewer']='Human reviewer; version labels hidden, formatting not fully blind'
    for row in scores['runs']:row.update(complete=True,supported=False,notes='missing source')
    imported=import_scores(r,m,mapping,scores)
    assert len(imported['runs'])==4
    assert all(row['complete'] and not row['supported'] for row in imported['runs'])
    assert audit(r,imported,m)['quality_counts']['efficient']['success']==0
    r[0]['report']['answer']='tampered'
    with pytest.raises(ValueError,match='match'):import_scores(r,m,mapping,scores)


def test_unscored_packet_cannot_be_imported():
    m,r,v=fixture();_,mapping,scores=review_packet(r,m);scores['reviewer']='Test'
    with pytest.raises(ValueError,match='booleans'):import_scores(r,m,mapping,scores)


def test_review_packet_is_bound_to_predeclared_rubric():
    m,r,v=fixture();_,mapping,scores=review_packet(r,m)
    m['settings']['rubric']['one']='A changed criterion'
    with pytest.raises(ValueError,match='rubric'):import_scores(r,m,mapping,scores)


def test_matching_pair_cannot_change_predeclared_question():
    m,r,v=fixture()
    for run in r:
        if run['case_id']=='one':run['question']='A different question'
    with pytest.raises(ValueError,match='predeclared'):audit(r,v,m)
