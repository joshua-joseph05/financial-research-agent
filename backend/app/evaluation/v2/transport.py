"""Local evaluation-only transport retaining raw responses, even on parse failure."""
import json,time
from copy import deepcopy
import httpx
from .rubric import SYSTEM

def constrained_schema(schema,context):
    output=deepcopy(schema.model_json_schema())
    if schema.__name__=='Claims':
        records={e['id'] for e in context['available_evidence']};variants=[]
        for claim in context['claims']:
            variant=deepcopy(output['$defs']['Claim'])
            variant['properties']['claim_id']={'type':'string','const':claim['id']}
            ids=sorted(set(claim['evidence_ids'])&records)
            citation=deepcopy(output['$defs']['Citation'])
            citation['properties']['evidence_id']={'type':'string','enum':ids} if ids else {'type':'string'}
            variant['properties']['citations']={'type':'array','minItems':len(ids),'maxItems':len(ids),'items':citation}
            variants.append(variant)
        output['properties']['claims']={'type':'array','minItems':len(variants),'maxItems':len(variants),'prefixItems':variants}
    if schema.__name__=='Task':
        variants=[]
        for criterion in context['criteria']:
            variant=deepcopy(output['$defs']['Criterion'])
            variant['properties']['criterion_id']={'type':'string','const':criterion['id']}
            variants.append(variant)
        output['properties']['criteria']={'type':'array','minItems':len(variants),'maxItems':len(variants),'prefixItems':variants}
    if schema.__name__=='CitationJudgments':
        variants=[]
        for association in context['citations']:
            variant=deepcopy(output['$defs']['CitationVerdict'])
            variant['properties']['citation_id']={'type':'string','const':association['citation_id']}
            variants.append(variant)
        output['properties']['citations']={'type':'array','minItems':len(variants),'maxItems':len(variants),'prefixItems':variants}
    return output

class OllamaJudge:
    def __init__(self,model='gemma4:e4b',base_url='http://127.0.0.1:11434'):
        if base_url not in ('http://127.0.0.1:11434','http://localhost:11434'):raise ValueError('Local Ollama only')
        if 'cloud' in model.lower() or '/' in model:raise ValueError('Downloaded models only')
        self.model=model;self.base_url=base_url
    def __call__(self,context,schema):
        with httpx.Client(base_url=self.base_url,trust_env=False,timeout=120) as client:
            info=client.post('/api/show',json={'model':self.model});info.raise_for_status()
            meta=info.json()
            if meta.get('remote_host') or meta.get('remote_model'):raise ValueError('Cloud models are disabled')
            payload={'model':self.model,'stream':False,'format':constrained_schema(schema,context),
                     'options':{'temperature':0,'num_predict':3072,'num_ctx':32768},
                     'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':json.dumps(context,ensure_ascii=False)}]}
            if 'thinking' in meta.get('capabilities',[]):payload['think']=False
            response=client.post('/api/chat',json=payload)
            # Preserve HTTP body before checking status or parsing its JSON.
            return {'status_code':response.status_code,'raw_response':response.text}


def judge_call(transport,context,schema,validator,max_attempts=2):
    attempts=[]
    for index in range(max_attempts):
        started=time.monotonic();attempt={'attempt':index+1,'raw_response':None,'raw_output':None,'parsed':None}
        try:
            retry_context=context if not attempts else {**context,'validation_correction':{'error':attempts[-1]['failure_reason'],'instruction':'Correct the schema/ID/quotation error. Do not add citations absent from the answer. Return the entire requested judgment again.'}}
            packet=transport(retry_context,schema);attempt.update(packet)
            if packet['status_code']!=200:raise ValueError('HTTP status '+str(packet['status_code']))
            envelope=json.loads(packet['raw_response'])
            attempt['raw_output']=envelope.get('message',{}).get('content')
            if not envelope.get('done') or envelope.get('done_reason')=='length':raise ValueError('Truncated/incomplete judge response')
            parsed=schema.model_validate_json(attempt['raw_output']).model_dump()
            attempt['parsed']=parsed
            validator(parsed,context)
            attempt['status']='valid';attempt['seconds']=time.monotonic()-started;attempts.append(attempt)
            return {'status':'ok','judgment':parsed,'retry_count':index,'attempts':attempts}
        except Exception as error:
            attempt.update(status='error',failure_type=type(error).__name__,failure_reason=str(error)[:1500],seconds=time.monotonic()-started)
            attempts.append(attempt)
    return {'status':'judge_error','judgment':None,'retry_count':max(0,len(attempts)-1),'attempts':attempts,
            'failure_reason':attempts[-1]['failure_reason']}


def assess_claims(transport,context,max_attempts=2):
    """Blind factual support to citations; assess citation associations independently."""
    from .rubric import Claims,CitationJudgments,CITATION_RULES,validate_claims,validate_citations
    from app.evaluation.judge import closure
    truth_context={**context,'claims':[{**c,'evidence_ids':[]} for c in context['claims']]}
    truth=judge_call(transport,truth_context,Claims,validate_claims,max_attempts)
    records={e['id']:e for e in context['available_evidence']}
    associations=[]
    for claim in context['claims']:
        for key in sorted(set(claim['evidence_ids'])&records.keys()):
            associations.append({'citation_id':claim['id']+'::'+key,'claim_id':claim['id'],'evidence_id':key,
                                 'claim_text':claim['text'],'evidence':list(closure([key],records).values())})
    citations=None
    if associations:
        citations=judge_call(transport,{'citations':associations,'instruction':CITATION_RULES},CitationJudgments,validate_citations,max_attempts)
    if truth['status']=='ok':
        merged=deepcopy(truth['judgment'])
        for claim in merged['claims']:
            claim['citations']=[]
            if citations and citations['status']=='ok':
                by_id={c['citation_id']:c for c in citations['judgment']['citations']}
                for association in associations:
                    if association['claim_id']==claim['claim_id']:
                        c=by_id[association['citation_id']]
                        claim['citations'].append({'evidence_id':association['evidence_id'],'supports':c['supports'],'reason':c['reason']})
        truth={**truth,'judgment':merged}
    return truth,citations
