"""Run: python -m app.evaluation.compare --case risks --budget 8 --repeats 1.
Uses live LLM calls but frozen, fictional tool fixtures. Never market advice.
"""
import argparse,json,hashlib,time,random
from pathlib import Path
from app.evaluation.fixtures import FixtureRegistry,snapshot,guide
from app.ideas.graph import run_ideas,SYSTEM
from app.ideas.models import IdeasRequest
from app.ideas.telemetry import MeteredModel
from app.providers.openrouter import create_model

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',default='risks');parser.add_argument('--budget',type=int,default=8)
    parser.add_argument('--repeats',type=int,default=1);parser.add_argument('--output',required=True)
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    if not 4<=args.budget<=48:parser.error('budget must be 4–48')
    cases=json.loads(Path(__file__).with_name('cases.json').read_text())
    cases=[c for c in cases if args.case=='all' or c['id']==args.case]
    if not cases:parser.error('Unknown case')
    if args.repeats<1 or args.repeats>3:parser.error('repeats must be 1–3')
    tasks=[(c,r,w) for c in cases for r in range(args.repeats) for w in ['single','sentiment']]
    random.Random(42).shuffle(tasks)
    print(f'{len(tasks)} runs; at most {len(tasks)*args.budget} model requests, including adapter retries.',flush=True)
    if args.dry_run:return
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    results=[];review=[]
    fixture_hash=hashlib.sha256(Path(__file__).with_name('fixtures.py').read_bytes()).hexdigest()
    for index,(case,repeat,workflow) in enumerate(tasks):
        model=MeteredModel(create_model(system_prompt=SYSTEM),args.budget)
        request=IdeasRequest(question=case['question'],tickers=case['tickers'],sentiment_enabled=workflow=='sentiment',max_model_requests=args.budget,research_size=3,horizon='5_plus_years',risk_tolerance='medium')
        label=f'report-{index+1:02d}'
        try:
            report=run_ideas(request,model,FixtureRegistry(),snapshot_fn=snapshot,guide_fn=guide)
            claims=[c for idea in report['ideas'] for c in idea['reasons']+idea['risks']]+report.get('answer_sections',[])
            known={e['id'] for e in report['evidence']}
            structural=sum(bool(c['evidence_ids']) and all(i in known for i in c['evidence_ids']) for c in claims)
            result={'label':label,'case':case['id'],'repeat':repeat,'workflow':workflow,'complete':report['complete'],'claims':len(claims),'claims_with_resolvable_citations':structural,'telemetry':report['telemetry'],'fixture_sha256':fixture_hash}
            # Blind review omits workflow, traces, provider self-review and timings.
            review.append({'label':label,'question':case['question'],'rubric':case['rubric'],'answer':claims,'evidence':report['evidence'],'limitations':report['limitations'],'scores':{'coverage_0_to_4':None,'citation_support_0_to_4':None,'numerical_accuracy_0_to_4':None,'readability_0_to_4':None,'unsupported_claim_count':None},'notes':''})
            (output/(label+'.json')).write_text(json.dumps(report,indent=2))
        except Exception as error:
            result={'label':label,'case':case['id'],'repeat':repeat,'workflow':workflow,'complete':False,'error':type(error).__name__,'telemetry':model.report(),'fixture_sha256':fixture_hash}
        results.append(result)
        (output/'results.json').write_text(json.dumps(results,indent=2))
        (output/'blind-review.json').write_text(json.dumps(review,indent=2))
        print(label,workflow,'complete:',result['complete'],'requests:',result['telemetry']['request_budget_used'],flush=True)
    print('Score blind-review.json before inspecting workflow labels in results.json. Citation resolution is NOT entailment or financial accuracy.')

if __name__=='__main__':main()
