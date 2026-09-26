"""Live semantic calibration on hand-written answers; never runs financial research."""
import argparse,json
from pathlib import Path
from .transport import OllamaJudge,judge_call,assess_claims,judge_task
from .rubric import Claims,Task,CLAIM_RULES,validate_claims,validate_task,task_context
from .engine import claim_result
from .rejudge import write

def fixtures():
    cases=[
        ('correct_citation','Acme revenue was 100 USD in 2025.',['r'],'supported'),
        ('missing_citation','Acme revenue was 100 USD in 2025.',[],'supported_missing_citation'),
        ('unsupported_cause','Acme revenue was 100 USD in 2025 because it acquired Rival.',[],'unsupported'),
        ('contradiction','Acme revenue was 200 USD in 2025.',['r'],'contradicted'),
        ('nonexistent_citation','Acme revenue was 100 USD in 2025.',['fake'],'supported_missing_citation'),
        ('irrelevant_citation','Acme revenue was 100 USD in 2025.',['s'],'supported_missing_citation'),
        ('procedural','Incomplete research: no_new_evidence',[],'nonfactual'),
        ('unjudgeable','Its prospects improved.',[],'unjudgeable')]
    return cases

def run(transport,output):
    evidence=[{'id':'r','text':'Acme revenue was 100 USD in 2025.'},{'id':'s','text':'Acme depends on one supplier.'}]
    results=[]
    for name,text,ids,expected in fixtures():
        context={'claims':[{'id':'c1','text':text,'evidence_ids':ids}],'available_evidence':evidence,'instruction':CLAIM_RULES}
        job,citation_job=assess_claims(transport,context)
        actual=claim_result(context['claims'][0],job['judgment']['claims'][0],{e['id']:e for e in evidence}) if job['status']=='ok' else {'classification':'judge_error'}
        results.append({'name':name,'expected':expected,'actual':actual,'passed':actual['classification']==expected and (not citation_job or citation_job['status']=='ok'),'job':job,'citation_job':citation_job})
        write(output,{'results':results});print(name,actual['classification'],flush=True)
    for name,text,expected in [('omitted_risks','The evidence includes the following risks:', 'fail'),
                               ('missing_input_refusal','The operating margin cannot be calculated because operating income is missing.','pass')]:
        case={'question':'What are Acme risks?' if name=='omitted_risks' else 'Calculate Apple operating margin with missing income.',
              'tickers':['ACME'] if name=='omitted_risks' else ['AAPL'],'expected_outcome':'answer' if name=='omitted_risks' else 'qualified_answer',
              'criteria':['Name the supply risks.'] if name=='omitted_risks' else ['Explain why missing income prevents calculation.','Ask a focused clarification when the intended company is unknown.']}
        context,waived=task_context(case,[{'id':'c1','text':text,'evidence_ids':[]}])
        job=judge_task(transport,context)
        actual=job['judgment']['criteria'][0]['verdict'] if job['status']=='ok' else 'judge_error'
        results.append({'name':name,'expected':expected,'actual':actual,'passed':actual==expected,'waived':waived,'job':job})
        write(output,{'results':results});print(name,actual,flush=True)
    summary={'results':results,'passed':sum(r['passed'] for r in results),'total':len(results)}
    write(output,summary);return summary

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--model',default='gemma4:e4b');args=parser.parse_args()
    if args.output.exists():parser.error('Choose a new output file')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    result=run(OllamaJudge(args.model),args.output)
    if result['passed']!=result['total']:raise SystemExit('Calibration disagreements require inspection before benchmark interpretation')
if __name__=='__main__':main()
