"""Citation bundles can jointly support a claim without each source proving everything."""
from copy import deepcopy
from pydantic import Field
from app.evaluation.v2.rubric import Strict,exact
from app.evaluation.v2.transport import judge_call,OllamaJudge
from app.evaluation.judge import closure
from app.evaluation.checks import rate
from app.evaluation.v2.engine import prepare,metrics
from . import VERSION

class BundleVerdict(Strict):
    claim_id:str
    reason:str=Field(min_length=5,max_length=360)
    supports_all:bool
class Bundles(Strict):
    claims:list[BundleVerdict]

RULES='''Judge whether ONLY the cited evidence, read collectively, supports the WHOLE claim. First inspect qualifiers: historical versus forecast, causal versus correlational, attribution, and dates. Explain any qualifier mismatch BEFORE discussing matching numbers. A matching number is insufficient.
Example: claim "Acme projects revenue of 150 in 2025"; evidence "Acme revenue was 150 in 2025". Verdict FALSE: the evidence is historical and never establishes a projection. Do not drop the word projects from the claim. The same rule applies to estimated, expects, forecast and projected.
Example: claim "Revenue rose from 100 to 150"; evidence records "Prior revenue 100" and "Current revenue 150". Verdict TRUE: the records jointly establish the comparison.
Example: claim "Revenue rose because of an acquisition"; evidence only revenue figures. Verdict FALSE: the cause is missing.
Return supports_all=true only when ALL material assertions and qualifiers are supported. Missing or irrelevant evidence is false. Do not use uncited evidence or outside knowledge. Generated interpretations and invalid calculations are not independent proof; follow valid source lineage. This assesses citations, not truth against other sources.'''

def validate(data,context):
    exact(data['claims'],'claim_id',[c['id'] for c in context['claims']])
    inputs={c['id']:c for c in context['claims']}
    for verdict in data['claims']:
        if verdict['supports_all'] and any(e.get('independent_calculation_check',{}).get('status')=='fail' for e in inputs[verdict['claim_id']]['cited_evidence']):
            raise ValueError('Invalid cited calculation lineage cannot establish citation correctness')
    return data

class BundleJudge(OllamaJudge):
    def __call__(self,context,schema):
        # Inline exact IDs and item count into a strict generated schema via a small facade.
        base=schema.model_json_schema();variants=[]
        for claim in context['claims']:
            item=deepcopy(base['$defs']['BundleVerdict']);item['properties']['claim_id']={'type':'string','const':claim['id']};variants.append(item)
        base['properties']['claims']={'type':'array','minItems':len(variants),'maxItems':len(variants),'prefixItems':variants}
        class Facade:
            @staticmethod
            def model_json_schema():return base
        # Parent transport passes other schemas through unchanged.
        return super().__call__(context,Facade)


def apply(claim,support,error=False):
    """Preserve truth; replace only citation results and supported/missing-citation label."""
    claim['prior_citation_assessment']={k:deepcopy(claim[k]) for k in ('citation_correctness','citation_complete','classification')}
    claim.pop('citation_error',None)
    if error:
        claim.update(citation_error=True,citation_correctness=rate(0,0),citation_complete=None)
    else:
        cited=claim['citation_validity']['total']>0
        claim.update(citation_correctness=rate(int(support),1) if cited else rate(0,0),citation_complete=bool(support) if claim['requires_citation'] else None)
    claim['classification']=claim['support']
    if claim['support']=='supported' and claim['requires_citation'] and not error and not support:claim['classification']='supported_missing_citation'
    return claim


def refine(pair,system,case,transport,save=None,cached=None):
    packet=prepare(pair['original'],system,case)
    result=cached or deepcopy(pair['corrected'][system])
    if not cached:
        result['prior_citation_jobs']=result.get('citation_jobs',[]);result['citation_jobs']=[]
        result['bundle_completed_ids']=[]
        result['version']=VERSION;result['component_versions']={'task':'answer-audit-v2.2','factual_support':'answer-audit-v2.2','citations':VERSION}
    originals={c['id']:c for c in packet['claims']};done=set(result['bundle_completed_ids']);todo=[]
    for claim in result['claims']:
        if claim['claim_id'] in done or claim['classification']=='judge_error' :continue
        if claim['support']=='nonfactual':
            claim.pop('citation_error',None)
            claim['citation_correctness']=rate(0,0)
            claim['citation_complete']=None
            result['bundle_completed_ids'].append(claim['claim_id'])
            continue
        source=originals[claim['claim_id']]
        evidence=list(closure(source['evidence_ids'],packet['records']).values())
        if not evidence:
            apply(claim,False);result['bundle_completed_ids'].append(claim['claim_id'])
        else:todo.append({'id':claim['claim_id'],'text':claim['text'],'cited_evidence':evidence})
    by_id={c['claim_id']:c for c in result['claims']}
    for start in range(0,len(todo),2):
        batch=todo[start:start+2];job=judge_call(transport,{'claims':batch,'instruction':RULES},Bundles,validate)
        result['citation_jobs'].append(job)
        if job['status']=='ok':
            for verdict in job['judgment']['claims']:
                apply(by_id[verdict['claim_id']],verdict['supports_all'])
                by_id[verdict['claim_id']]['bundle_reason']=verdict['reason']
        else:
            for claim in batch:apply(by_id[claim['id']],False,error=True)
        result['bundle_completed_ids'].extend(c['id'] for c in batch)
        if save:save(result)
    result['metrics']=metrics(result,packet['claims'],packet['records'])
    result['bundle_complete']=True
    if save:save(result)
    return result
