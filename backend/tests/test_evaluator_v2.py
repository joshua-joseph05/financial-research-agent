"""Hand-annotated grading contracts: no network or answering-model calls."""
import json
import pytest
from app.evaluation.v2.rubric import Claims,Task,validate_claims,validate_task,task_context
from app.evaluation.v2.transport import judge_call
from app.evaluation.v2.engine import claim_result
from app.evaluation.checks import calculation_check

EVIDENCE=[{'id':'revenue','text':'Acme revenue was 100 USD in 2025.'},
          {'id':'risks','text':'Acme relies on a single supplier.'}]

def annotated(support,refs,witnesses=None):
    return {'claim_id':'c1','support':support,'requires_citation':support not in ('nonfactual','unjudgeable'),
            'witnesses':witnesses or [],'citations':refs,'reason':'Hand-annotated against the supplied source.'}
def checked(text,ids,rating):
    context={'claims':[{'id':'c1','text':text,'evidence_ids':ids}],'available_evidence':EVIDENCE}
    data=Claims.model_validate({'claims':[rating]}).model_dump()
    validate_claims(data,context)
    return claim_result(context['claims'][0],rating,{e['id']:e for e in EVIDENCE})
W=[{'evidence_id':'revenue','quote':'revenue was 100 USD'}]
C=[{'evidence_id':'revenue','supports':True,'reason':'Exact revenue and period.'}]

def test_supported_correct_citation():
    r=checked('Acme revenue was 100 USD in 2025.',['revenue'],annotated('supported',C,W))
    assert r['classification']=='supported' and r['citation_complete']
    assert r['citation_correctness']['rate']==r['citation_validity']['rate']==1

def test_supported_missing_citation_is_not_unsupported():
    r=checked('Acme revenue was 100 USD in 2025.',[],annotated('supported',[],W))
    assert r['support']=='supported' and r['classification']=='supported_missing_citation'
    assert r['citation_complete'] is False

def test_unsupported_extra_assertion_is_not_contradiction():
    r=checked('Acme revenue growth was caused by an acquisition.',[],annotated('unsupported',[]))
    assert r['classification']=='unsupported'

def test_contradiction_requires_conflicting_source():
    r=checked('Acme revenue was 200 USD in 2025.',[],annotated('contradicted',[],W))
    assert r['classification']=='contradicted'
    with pytest.raises(ValueError,match='witness'):
        checked('Acme revenue was 200 USD.',[],annotated('contradicted',[]))

def test_nonexistent_citation_is_invalid_but_claim_can_be_supported():
    r=checked('Acme revenue was 100 USD in 2025.',['fake'],annotated('supported',[],W))
    assert r['citation_validity']['rate']==0
    assert r['invalid_citation_ids']==['fake'] and r['support']=='supported'

def test_irrelevant_existing_citation_fails_correctness_not_support():
    r=checked('Acme revenue was 100 USD in 2025.',['risks'],annotated('supported',[{'evidence_id':'risks','supports':False,'reason':'Supplier evidence does not give revenue.'}],W))
    assert r['citation_validity']['rate']==1 and r['citation_correctness']['rate']==0
    assert r['classification']=='supported_missing_citation'

def test_procedural_notice_has_no_financial_truth_or_citation_penalty():
    r=checked('Incomplete research: no_new_evidence',[],annotated('nonfactual',[]))
    assert r['classification']=='nonfactual' and r['citation_complete'] is None

def test_unjudgeable_claim_is_not_false():
    r=checked('Its prospects improved.',[],annotated('unjudgeable',[]))
    assert r['classification']=='unjudgeable'

def test_completion_cannot_quote_evidence_absent_from_answer():
    case={'question':'What are Acme risks?','expected_outcome':'answer','tickers':['ACME'],'criteria':['Name the supply risks.']}
    context,_=task_context(case,[{'id':'c1','text':'The evidence contains the following risks:','evidence_ids':['risks']}])
    assert 'available_evidence' not in context
    data={'criteria':[{'criterion_id':'criterion-1','verdict':'pass','answer_quotes':['Acme relies on a single supplier.'],'reason':'This text only exists in the evidence.'}]}
    with pytest.raises(ValueError,match='not in the final answer'):validate_task(data,context)
    data['criteria'][0].update(verdict='fail',answer_quotes=[],reason='The answer does not actually name any risk.')
    validate_task(data,context)

def test_missing_input_refusal_and_conditional_company_clarification():
    case={'question':'Calculate Apple margin with missing income.','expected_outcome':'qualified_answer','tickers':['AAPL'],
          'criteria':['State that the missing income prevents calculation.','Ask a focused clarification when the intended company is unknown.']}
    text='I cannot calculate operating margin because operating income is missing.'
    context,waived=task_context(case,[{'id':'c1','text':text,'evidence_ids':[]}])
    assert len(waived)==1 and len(context['criteria'])==1
    data={'criteria':[{'criterion_id':'criterion-1','verdict':'pass','answer_quotes':[text],'reason':'Explicit and appropriate missing-input refusal.'}]}
    validate_task(data,context)
    # Changing system identity cannot affect applicability: none is an input.
    assert task_context(case,context['answer'])==(context,waived)

def test_correct_number_and_lineage():
    inputs={'new':{'id':'new','ticker':'ACME','metric':'revenue','value':'150','period':'2025','unit':'USD'},
            'old':{'id':'old','ticker':'ACME','metric':'revenue','value':'100','period':'2024','unit':'USD'}}
    result={'id':'growth','operation':'growth','input_ids':['new','old'],'ticker':'ACME','period':'2025','value':'50.0000','unit':'percent'}
    assert calculation_check(result,inputs)['status']=='pass'
    # Same correct visible number with reversed lineage must fail independently.
    assert calculation_check({**result,'input_ids':['old','new']},inputs)['status']=='fail'

class Responses:
    def __init__(self,responses):self.responses=iter(responses);self.calls=0
    def __call__(self,*args):
        self.calls+=1;value=next(self.responses)
        if isinstance(value,Exception):raise value
        return value

def envelope(content,**kwargs):
    return {'status_code':200,'raw_response':json.dumps({'done':True,'done_reason':'stop','message':{'content':content},**kwargs})}

@pytest.mark.parametrize('failure',[envelope('{broken'),envelope('{}'),envelope('{"claims":[]}'),
    envelope('{"claims":[]}',done_reason='length'),TimeoutError('Local timeout'),
    {'status_code':503,'raw_response':'unavailable'},
    envelope(json.dumps({'claims':[{'claim_id':'c1','support':'made_up'}]}))])
def test_bounded_retry_retains_raw_failures_and_valid_recovery(failure):
    context={'claims':[{'id':'c1','text':'Incomplete research.','evidence_ids':[]}],'available_evidence':[]}
    good={'claims':[annotated('nonfactual',[])]}
    transport=Responses([failure,envelope(json.dumps(good))])
    result=judge_call(transport,context,Claims,validate_claims)
    assert result['status']=='ok' and result['retry_count']==1 and transport.calls==2
    assert result['attempts'][0]['failure_reason']
    assert result['attempts'][1]['parsed']==good
    assert result['attempts'][1]['raw_output']==json.dumps(good)

def test_exhausted_retries_are_evaluator_error_not_system_failure():
    transport=Responses([TimeoutError('timeout'),TimeoutError('timeout')])
    result=judge_call(transport,{},Claims,validate_claims)
    assert result['status']=='judge_error' and result['judgment'] is None and transport.calls==2
    assert 'system_status' not in result


def test_unknown_evidence_witness_and_duplicate_claim_ids_rejected():
    with pytest.raises(ValueError,match='Unknown evidence'):
        checked('Revenue is 100.',[],annotated('supported',[],[{'evidence_id':'fake','quote':'100'}]))
    r=annotated('nonfactual',[])
    with pytest.raises(ValueError,match='duplicate'):
        validate_claims({'claims':[r,r]},{'claims':[{'id':'c1','evidence_ids':[]}],'available_evidence':[]})

def test_incomplete_judgments_do_not_turn_into_quality_failures():
    from app.evaluation.v2.engine import metrics
    job={'status':'judge_error','judgment':None,'attempts':[{'status':'error'}]*2,'retry_count':1}
    result={'task':job,'claim_jobs':[job],'claims':[{'classification':'judge_error'}],
            'calculations':{'metric':{'passed':0,'total':0,'rate':None}}}
    scores=metrics(result,[{'id':'c1','evidence_ids':[]}],{})
    assert scores['task_completion']['rate'] is None
    assert scores['unsupported_claim_rate']['rate'] is None
    assert scores['supported_claim_rate']['rate'] is None
    assert scores['judge_error_rate']['rate']==1
    assert scores['claim_assessment_coverage']['rate']==0

def test_procedural_and_unjudgeable_excluded_from_factual_rates():
    from app.evaluation.v2.engine import metrics
    claims=[{'id':'c1','text':'notice','evidence_ids':[]},{'id':'c2','text':'ambiguous','evidence_ids':[]}]
    outputs=[]
    for claim,kind in zip(claims,['nonfactual','unjudgeable']):
        outputs.append(claim_result(claim,{**annotated(kind,[]),'claim_id':claim['id']},{}))
    job={'status':'ok','judgment':{'criteria':[{'verdict':'pass'}]},'attempts':[{'status':'valid'}],'retry_count':0}
    result={'task':job,'claim_jobs':[job],'claims':outputs,'calculations':{'metric':{'passed':0,'total':0,'rate':None}}}
    scores=metrics(result,claims,{})
    assert scores['unsupported_claim_rate']['total']==0
    assert scores['unjudgeable_claims']==scores['procedural_claims']==1
    assert scores['evaluated_claims']==2

def test_generated_interpretation_is_not_independent_ground_truth():
    context={'claims':[{'id':'c1','text':'Profit doubled.','evidence_ids':['arg']}],
             'available_evidence':[{'id':'arg','text':'Profit doubled.','kind':'generated_interpretation'}]}
    rating=annotated('supported',[{'evidence_id':'arg','supports':True,'reason':'An interpretation.'}],[{'evidence_id':'arg','quote':'Profit doubled.'}])
    with pytest.raises(ValueError,match='independent witness'):validate_claims({'claims':[rating]},context)

def test_output_schema_prevents_invented_citations_for_uncited_answer():
    from app.evaluation.v2.transport import constrained_schema
    context={'claims':[{'id':'c1','evidence_ids':[]}],'available_evidence':EVIDENCE}
    schema=constrained_schema(Claims,context)
    variant=schema['properties']['claims']['prefixItems'][0]
    assert variant['properties']['claim_id']['const']=='c1'
    assert variant['properties']['citations']['maxItems']==0

def test_retry_receives_validation_feedback():
    contexts=[]
    def transport(context,schema):
        contexts.append(context)
        return envelope('{}')
    result=judge_call(transport,{},Claims,validate_claims)
    assert result['status']=='judge_error'
    assert 'validation_correction' not in contexts[0]
    assert contexts[1]['validation_correction']['error']

def test_factual_support_is_blind_to_irrelevant_answer_citation():
    from app.evaluation.v2.transport import assess_claims
    seen=[]
    def transport(context,schema):
        seen.append((schema.__name__,context))
        if schema.__name__=='Claims':
            assert context['claims'][0]['evidence_ids']==[]
            return envelope(json.dumps({'claims':[annotated('supported',[],W)]}))
        associations=context['citations']
        return envelope(json.dumps({'citations':[{'citation_id':a['citation_id'],'reason':'Supplier text does not establish revenue.','supports':False} for a in associations]}))
    context={'claims':[{'id':'c1','text':'Acme revenue was 100 USD in 2025.','evidence_ids':['risks']}],
             'available_evidence':EVIDENCE,'instruction':'audit'}
    support,citations=assess_claims(transport,context)
    result=claim_result(context['claims'][0],support['judgment']['claims'][0],{e['id']:e for e in EVIDENCE})
    assert result['support']=='supported' and result['classification']=='supported_missing_citation'
    assert result['citation_correctness']['rate']==0
    assert [s for s,c in seen]==['Claims','CitationJudgments']
    assert context['claims'][0]['evidence_ids']==['risks']


def test_citation_failure_does_not_erase_valid_factual_judgment():
    from app.evaluation.v2.transport import assess_claims
    def transport(context,schema):
        if schema.__name__=='Claims':return envelope(json.dumps({'claims':[annotated('supported',[],W)]}))
        raise TimeoutError('Citation judge unavailable')
    context={'claims':[{'id':'c1','text':'Acme revenue was 100 USD in 2025.','evidence_ids':['revenue']}],'available_evidence':EVIDENCE}
    truth,citations=assess_claims(transport,context)
    assert truth['status']=='ok' and citations['status']=='judge_error'
    assert truth['judgment']['claims'][0]['support']=='supported'
    assert len(citations['attempts'])==2

def test_rejudge_cli_preserves_original_answers_and_resumes_without_calls(tmp_path,monkeypatch):
    import sys
    from test_benchmark import case,ResearchModel,Judge
    from test_baseline import BaselineModel
    from app.evaluation.recording import run_case
    from app.evaluation.baseline_compare import compare_pair
    from app.evaluation.baseline_report import comparison_summary
    import app.evaluation.v2.rejudge as cli
    agent=run_case(case(),ResearchModel(),budget=16);agent['label']='001-sec_filings-01-enabled-r1'
    pair=compare_pair(case(),agent,BaselineModel(),Judge)
    source=tmp_path/'source';source.mkdir();output=tmp_path/'v2'
    (source/(pair['id']+'.json')).write_text(json.dumps(pair))
    (source/'manifest.json').write_text(json.dumps({'source_manifest':{'cases':[case().model_dump()]}}))
    (source/'comparison.json').write_text(json.dumps(comparison_summary([pair],{'sec_filings':1})))
    (source/'comparison.md').write_text('Historical report must stay byte-identical.')
    before={p.name:p.read_bytes() for p in source.iterdir()}
    calls=[]
    def fake(context,schema):
        calls.append(schema.__name__)
        if schema.__name__=='Task':
            data={'criteria':[{'criterion_id':c['id'],'verdict':'pass','answer_quotes':[context['answer'][0]['text']],
                              'reason':'Integration fixture; semantic calibration is separate.'} for c in context['criteria']]}
        elif schema.__name__=='Claims':
            data={'claims':[{**annotated('nonfactual',[]),'claim_id':c['id']} for c in context['claims']]}
        else:data={'citations':[{'citation_id':c['citation_id'],'reason':'Integration fixture association.','supports':False} for c in context['citations']]}
        return envelope(json.dumps(data))
    monkeypatch.setattr(cli,'OllamaJudge',lambda model:fake)
    argv=['rejudge','--source',str(source),'--output',str(output),'--max-requests','1000']
    monkeypatch.setattr(sys,'argv',argv);cli.main()
    result=json.loads((output/'comparison-v2.json').read_text())
    assert result['recorded_pairs']==result['planned_pairs']==1
    saved=json.loads((output/(pair['id']+'-v2.json')).read_text())
    assert saved['original']==pair
    assert all((source/name).read_bytes()==content for name,content in before.items())
    assert all((output/'original'/name).read_bytes()==content for name,content in before.items())
    assert (output/'evaluator_snapshot/v1_judge.py').is_file()
    count=len(calls)
    monkeypatch.setattr(sys,'argv',argv+['--resume']);cli.main()
    assert len(calls)==count
    assert json.loads((output/'comparison-v2.json').read_text())==result

def test_task_schema_requires_every_criterion_and_citation_schema_every_association():
    from app.evaluation.v2.transport import constrained_schema
    from app.evaluation.v2.rubric import CitationJudgments
    context={'criteria':[{'id':f'criterion-{i}'} for i in (1,2,3)]}
    items=constrained_schema(Task,context)['properties']['criteria']
    assert items['minItems']==items['maxItems']==3
    assert [i['properties']['criterion_id']['const'] for i in items['prefixItems']]==['criterion-1','criterion-2','criterion-3']
    citations=constrained_schema(CitationJudgments,{'citations':[{'citation_id':'a'},{'citation_id':'b'}]})['properties']['citations']
    assert citations['minItems']==citations['maxItems']==2
    assert [i['properties']['citation_id']['const'] for i in citations['prefixItems']]==['a','b']
