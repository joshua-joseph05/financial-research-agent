"""Rejudge immutable saved answers; no production execution dependencies."""
from copy import deepcopy
from . import VERSION
from .rubric import Claims,Task,CLAIM_RULES,validate_claims,validate_task,task_context
from .transport import judge_call,assess_claims
from app.evaluation.checks import answer_claims,evidence_inventory,rate
from app.evaluation.baseline import answer_calculations,evidence_bundle


def prepare(pair,system,case):
    run=pair[system];claims=answer_claims(run)
    bundle,_=evidence_bundle(pair['agent'])
    records={e['id']:deepcopy(e) for e in bundle['evidence']}
    own,_=evidence_inventory(run)
    # Derived sentiment IDs are valid references, but interpretations are not independent proof.
    for sample in run['trace'].get('sentiment_results',[]):
        for argument in sample.get('arguments',[]):
            key=argument['id']
            if key in own:records[key]={**own[key],'kind':'generated_interpretation'}
    # Generated calculations are answer output; retain and label their independently checked lineage.
    calculations=answer_calculations(run)
    for detail in calculations['details']:
        if detail['id'] in own:
            records[detail['id']]={**own[detail['id']], 'independent_calculation_check':detail}
    # Process/source limitations describe evidence availability, never source financial facts.
    for i,text in enumerate(dict.fromkeys(bundle['source_limitations'])):
        records[f'evaluation:source-limitation-{i+1}']={'id':f'evaluation:source-limitation-{i+1}','text':text,'kind':'source_availability'}
    task,waived=task_context(case,claims)
    return {'claims':claims,'records':records,'task':task,'waived':waived,'calculations':calculations}


def claim_result(claim,judgment,records):
    refs=list(dict.fromkeys(claim['evidence_ids']))
    valid=[r for r in refs if r in records]
    correct=[c['evidence_id'] for c in judgment['citations'] if c['supports']]
    classification=judgment['support']
    if classification=='supported' and judgment['requires_citation'] and not correct:
        classification='supported_missing_citation'
    return {**judgment,'classification':classification,'text':claim['text'],
            'citation_validity':rate(len(valid),len(refs)),
            'citation_correctness':rate(len(correct),len(valid)),
            'citation_complete':bool(correct) if judgment['requires_citation'] else None,
            'invalid_citation_ids':[r for r in refs if r not in records]}


def metrics(result,claims,records):
    evaluated=[c for c in result['claims'] if c['classification']!='judge_error']
    factual=[c for c in evaluated if c['support'] in ('supported','unsupported','contradicted')]
    required=[c for c in evaluated if c['requires_citation'] and c['citation_complete'] is not None]
    refs=[r for c in claims for r in set(c['evidence_ids'])]
    correctness=[c for c in evaluated if c['requires_citation']]
    task=result['task']
    criteria=(task.get('judgment') or {}).get('criteria',[])
    task_assessed=task['status']=='ok' and all(c['verdict']!='unjudgeable' for c in criteria)
    jobs=[result['task']]+result['claim_jobs']+result.get('citation_jobs',[])
    return {
        'task_completion':rate(int(all(c['verdict']=='pass' for c in criteria)),1) if task_assessed else rate(0,0),
        'citation_validity':rate(sum(r in records for r in refs),len(refs)),
        'citation_correctness':rate(sum(c['citation_correctness']['passed'] for c in correctness),sum(c['citation_correctness']['total'] for c in correctness)),
        'citation_completeness':rate(sum(c['citation_complete'] for c in required),len(required)),
        'supported_claim_rate':rate(sum(c['support']=='supported' for c in factual),len(factual)),
        'unsupported_claim_rate':rate(sum(c['support']=='unsupported' for c in factual),len(factual)),
        'contradicted_claim_rate':rate(sum(c['support']=='contradicted' for c in factual),len(factual)),
        'claim_assessment_coverage':rate(len(evaluated),len(claims)),
        'calculation_accuracy':result['calculations']['metric'],
        'judge_success_rate':rate(sum(j['status']=='ok' for j in jobs),len(jobs)),
        'judge_error_rate':rate(sum(j['status']=='judge_error' for j in jobs),len(jobs)),
        'retry_frequency':rate(sum(j['retry_count']>0 for j in jobs),len(jobs)),
        'unjudgeable_claims':sum(c['support']=='unjudgeable' for c in evaluated),
        'procedural_claims':sum(c['support']=='nonfactual' for c in evaluated),
        'citation_judge_errors':sum(c.get('citation_error',False) for c in evaluated),
        'evaluated_claims':len(evaluated),'total_claims':len(claims),
        'judge_attempts':sum(len(j['attempts']) for j in jobs),
    }


def evaluate(pair,system,case,transport,save=None,cached=None,max_attempts=2):
    packet=prepare(pair,system,case)
    result=cached or {'version':VERSION,'system_status':pair[system]['status'],'claims':[],'claim_jobs':[],'citation_jobs':[],
        'waived_criteria':packet['waived'],'calculations':packet['calculations'],'max_attempts':max_attempts}
    if 'task' not in result:
        result['task']=judge_call(transport,packet['task'],Task,validate_task,max_attempts)
        if save:save(result)
    done={c['claim_id'] for c in result['claims']}
    todo=[c for c in packet['claims'] if c['id'] not in done]
    for start in range(0,len(todo),2):
        batch=todo[start:start+2]
        context={'claims':batch,'available_evidence':list(packet['records'].values()),'instruction':CLAIM_RULES}
        job,citation_job=assess_claims(transport,context,max_attempts)
        if citation_job:result['citation_jobs'].append(citation_job)
        result['claim_jobs'].append(job)
        if job['status']=='ok':
            by_id={c['claim_id']:c for c in job['judgment']['claims']}
            for c in batch:
                graded=claim_result(c,by_id[c['id']],packet['records'])
                if citation_job and citation_job['status']=='judge_error' and set(c['evidence_ids'])&packet['records'].keys():
                    graded.update(citation_error=True,citation_complete=None,citation_correctness=rate(0,0),classification=by_id[c['id']]['support'])
                result['claims'].append(graded)
        else:
            result['claims'].extend({'claim_id':c['id'],'text':c['text'],'classification':'judge_error','failure_reason':job['failure_reason']} for c in batch)
        if save:save(result)
    result['metrics']=metrics(result,packet['claims'],packet['records'])
    if save:save(result)
    return result
