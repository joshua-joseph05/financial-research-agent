from copy import deepcopy
from app.evaluation.v23.citations import apply,refine
from app.evaluation.checks import rate

def claim(refs=2):
    return {'support':'supported','classification':'supported_missing_citation','requires_citation':True,
            'citation_validity':rate(refs,refs),'citation_correctness':rate(0,refs),'citation_complete':False}

def test_joint_support_replaces_unfair_standalone_reference_penalty():
    c=claim();apply(c,True)
    assert c['citation_correctness']==rate(1,1)
    assert c['citation_complete'] and c['classification']=='supported'
    assert c['prior_citation_assessment']['citation_correctness']==rate(0,2)

def test_missing_citation_changes_completeness_not_factual_support():
    c=claim(0);apply(c,False)
    assert c['support']=='supported' and c['classification']=='supported_missing_citation'
    assert c['citation_correctness']['rate'] is None and c['citation_complete'] is False

def test_failed_bundle_judge_preserves_truth_and_excludes_citation_score():
    c=claim();apply(c,False,error=True)
    assert c['support']=='supported' and c['citation_error']
    assert c['citation_correctness']['rate'] is None and c['citation_complete'] is None

def test_incomplete_bundle_is_not_automatically_false_claim():
    c=claim();apply(c,False)
    assert c['support']=='supported' and c['citation_correctness']['rate']==0


def test_bundle_schema_rejects_missing_fields_and_coerced_boolean():
    import pytest
    from pydantic import ValidationError
    from app.evaluation.v23.citations import Bundles
    for verdict in ({'claim_id':'c','supports_all':True},
                    {'claim_id':'c','reason':'Correct evidence','supports_all':'true'}):
        with pytest.raises(ValidationError):
            Bundles.model_validate({'claims':[verdict]})


def test_bundle_validation_rejects_missing_or_wrong_claim_ids():
    import pytest
    from app.evaluation.v23.citations import validate
    for claims in ([], [{'claim_id':'different'}]):
        with pytest.raises(ValueError):
            validate({'claims':claims},{'claims':[{'id':'c'}]})


def test_joint_evidence_is_preserved_in_transport_and_schema(monkeypatch):
    from app.evaluation.v23.citations import BundleJudge,Bundles
    from app.evaluation.v2.transport import OllamaJudge
    seen=[]
    def fake(self,context,schema):
        seen.append((context,schema.model_json_schema()))
        return {'status_code':200,'raw_response':'{}'}
    monkeypatch.setattr(OllamaJudge,'__call__',fake)
    context={'claims':[{'id':'c','text':'Revenue increased from 100 to 150.',
        'cited_evidence':[{'id':'a','text':'Prior revenue: 100.'},{'id':'b','text':'Current revenue: 150.'}]}]}
    BundleJudge()(context,Bundles)
    assert seen[0][0]==context
    array=seen[0][1]['properties']['claims']
    assert array['minItems']==array['maxItems']==1
    assert array['prefixItems'][0]['properties']['claim_id']['const']=='c'


def test_bundle_retries_preserve_raw_failed_output():
    import json
    from app.evaluation.v23.citations import Bundles,validate
    from app.evaluation.v2.transport import judge_call
    outputs=iter(['{truncated',json.dumps({'claims':[{'claim_id':'c','reason':'Both cited records jointly support the change.','supports_all':True}]})])
    def fake(context,schema):
        return {'status_code':200,'raw_response':json.dumps({'done':True,'message':{'content':next(outputs)}})}
    result=judge_call(fake,{'claims':[{'id':'c','cited_evidence':[]}]},Bundles,validate)
    assert result['status']=='ok' and result['retry_count']==1
    assert result['attempts'][0]['raw_output']=='{truncated'
    assert result['attempts'][0]['failure_reason']


def test_claim_not_requiring_citation_has_no_completeness_penalty():
    c=claim(0);c['requires_citation']=False
    apply(c,False)
    assert c['citation_complete'] is None and c['classification']=='supported'


def test_calibration_gate_can_detect_semantically_wrong_well_formed_judge(tmp_path):
    import json
    from app.evaluation.v23.calibrate import run
    def overconfident(context,schema):
        payload={'claims':[{'claim_id':'c','reason':'Always says supported regardless of evidence.','supports_all':True}]}
        return {'status_code':200,'raw_response':json.dumps({'done':True,'message':{'content':json.dumps(payload)}})}
    output=tmp_path/'calibration.json'
    assert run(overconfident,output) is False
    saved=json.loads(output.read_text())
    assert saved['passed']==1 and saved['total']==4


def test_correct_number_with_invalid_cited_lineage_cannot_pass_bundle_validation():
    import pytest
    from app.evaluation.v23.citations import validate
    context={'claims':[{'id':'c','cited_evidence':[{'id':'calc', 'value':'50',
        'independent_calculation_check':{'status':'fail','reason':'Reversed input periods'}}]}]}
    with pytest.raises(ValueError,match='Invalid cited calculation lineage'):
        validate({'claims':[{'claim_id':'c','supports_all':True}]},context)
    validate({'claims':[{'claim_id':'c','supports_all':False}]},context)
