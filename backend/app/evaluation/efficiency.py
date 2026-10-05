"""Paired standard-versus-efficient agent experiment; both retrieve frozen evidence."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
from statistics import mean,median
import time
import fcntl
from app.evaluation.benchmark_data import load_cases
from app.evaluation.benchmark import fingerprint
from app.evaluation.recording import run_case
from app.evaluation.checks import answer_claims
from app.evaluation.v2.rejudge import write
from app.providers.llm import OllamaModel
from app.ideas.graph import SYSTEM
from app.assistant import Route

DEV={'education-01','education-03','education-05','education-07','education-09'}
VALIDATION={'education-02','education-04','education-06','education-08','education-10'}
CRITERIA={
'education-01':'Explain spreading investments to reduce concentration risk and that losses remain possible.',
'education-02':'Explain that diversification does not prevent all losses, while reducing concentration risk.',
'education-03':'Explain that stock ownership is ownership in a company.',
'education-04':'State that dividends are not guaranteed.',
'education-05':'Explain that a bond is a loan to an issuer.',
'education-06':'Explain that bond prices can fall when interest rates rise; do not predict rates.',
'education-07':'Explain that an ETF is a pooled investment fund traded on an exchange.',
'education-08':'Explain how pooled funds can spread holdings, without implying all funds are diversified.',
'education-09':'Explain that fees reduce the money retained by investors.',
'education-10':'Contrast company ownership through stocks with lending to an issuer through bonds.'}


def answer_hash(run):
    answer=run.get('report')
    if answer is None:
        answer={key:run.get(key) for key in ('status','clarification','errors')}
    return hashlib.sha256(json.dumps(answer,sort_keys=True).encode()).hexdigest()


def summarize(output,runs,review=None,development=None,validation=None):
    development = DEV if development is None else set(development)
    validation = VALIDATION if validation is None else set(validation)
    labels={(r['case_id'],r['execution_profile']):r for r in runs}
    checks={}
    if review:
        for item in json.loads(review.read_text())['runs']:
            key=(item['case_id'],item['profile'])
            if key in checks or key not in labels:raise ValueError('Unknown or duplicate review item')
            if item['answer_sha256']!=answer_hash(labels[key]):raise ValueError('Review does not match saved answer')
            for field in ('complete','supported'):
                if item[field] is not None and type(item[field]) is not bool:raise ValueError('Review scores must be booleans or null')
            checks[key]=item
    rows={}
    groups=[('development',development),('validation',validation),('all',development|validation)]
    for category in sorted({r['category'] for r in runs}):
        category_ids={r['case_id'] for r in runs if r['category']==category}
        groups += [('development/'+category,development & category_ids),('validation/'+category,validation & category_ids)]
    for split,ids in groups:
        paired=[key for key in sorted(ids) if all((key,s) in labels for s in ('standard','efficient'))]
        assessed=[key for key in paired if all(checks.get((key,s),{}).get('complete') is not None and checks.get((key,s),{}).get('supported') is not None for s in ('standard','efficient'))]
        rows[split]={'paired_questions':len(paired),'reviewed_pairs':len(assessed),'profiles':{}}
        for profile in ('standard','efficient'):
            samples=[labels[(key,profile)] for key in paired];latencies=sorted(r['latency_seconds'] for r in samples)
            known_tokens=[r['telemetry'].get('tokens',{}).get('total_tokens') for r in samples]
            known_tokens=[t if type(t) in (int,float) and math.isfinite(t) and t>=0 else None for t in known_tokens]
            total_tokens=sum(known_tokens) if samples and all(t is not None for t in known_tokens) else None
            successes=sum(checks[(key,profile)]['complete'] and checks[(key,profile)]['supported'] for key in assessed)
            rows[split]['profiles'][profile]={
                'mean_model_calls':mean(r['telemetry']['model_calls'] for r in samples) if samples else None,
                'mean_latency_seconds':mean(latencies) if latencies else None,
                'median_latency_seconds':median(latencies) if latencies else None,
                'p95_latency_seconds':latencies[math.ceil(.95*len(latencies))-1] if latencies else None,
                'mean_total_tokens':mean(t for t in known_tokens if t is not None) if any(t is not None for t in known_tokens) else None,
                'token_coverage':sum(t is not None for t in known_tokens),
                'total_tokens':total_tokens,
                'reviewed_supported_completions':successes,
                'tokens_per_supported_completion':total_tokens/successes if total_tokens is not None and successes and len(assessed)==len(paired) else None,
                'errors':sum(r['status']=='error' for r in samples),
                'reviewed_completion':sum(checks[(key,profile)]['complete'] for key in assessed),
                'reviewed_supported_answers':sum(checks[(key,profile)]['supported'] for key in assessed)}
    validation_count=len(validation)
    validation=rows['validation']
    if not validation_count or validation['reviewed_pairs']!=validation_count:
        gate={'status':'awaiting_validation_review','reason':'All reserved validation pairs need separate completion and factual-support review.'}
    else:
        a,b=[validation['profiles'][p] for p in ('standard','efficient')]
        quality=(b['reviewed_completion']>=a['reviewed_completion'] and b['reviewed_supported_answers']==validation_count and b['errors']==0)
        category_nonregression=all(row['profiles']['efficient']['reviewed_completion'] >= row['profiles']['standard']['reviewed_completion'] and row['profiles']['efficient']['reviewed_supported_answers'] >= row['profiles']['standard']['reviewed_supported_answers'] for key,row in rows.items() if key.startswith('validation/') and row['reviewed_pairs'])
        quality=quality and category_nonregression
        efficient=(b['mean_model_calls']<a['mean_model_calls'] and b['median_latency_seconds']<a['median_latency_seconds'] and b['p95_latency_seconds']<=a['p95_latency_seconds'])
        token_known=all(p['token_coverage']==validation_count for p in (a,b))
        ratio_known=all(p['tokens_per_supported_completion'] is not None for p in (a,b))
        token_nonregression=token_known and ratio_known and b['total_tokens']<=a['total_tokens'] and b['tokens_per_supported_completion']<=a['tokens_per_supported_completion']
        gate={'status':'promising_small_sample' if quality and efficient and token_nonregression else 'do_not_promote',
              'token_usage_complete':token_known,'success_cost_comparable':ratio_known,'token_cost_nonregression':token_nonregression,
              'quality_nonregression':quality,'category_quality_nonregression':category_nonregression,'measured_efficiency_gain':efficient,
              'reason':'No automatic rollout. Validate additional cases and repeated timing runs before broader use.'}
    result={'comparison':'Both agents collect their own evidence; same model, frozen sources and questions. No inherited-evidence baseline.','metrics':rows,'gate':gate,'reviewer':json.loads(review.read_text()).get('reviewer') if review else None}
    write(output/'summary.json',result)
    lines=['# Agent efficiency experiment','','Both profiles retrieve evidence and retain source review. The standard profile is the reference path in this source snapshot; efficient is opt-in.','',
           'Quality is unassessed until a separate reviewer supplies completion and support decisions against the predeclared rubric. The agent’s own complete flag is not a quality score.','']
    for split,row in rows.items():
        lines += [f"## {split}: {row['paired_questions']} paired questions",'', '| Measure | Standard | Efficient |','| --- | ---: | ---: |']
        for key in row['profiles']['standard']:
            lines.append(f"| {key} | {row['profiles']['standard'][key]} | {row['profiles']['efficient'][key]} |")
        lines += ['',f"Quality denominator: {row['reviewed_pairs']} jointly reviewed pairs. Zero reviewed successes with zero assessed pairs means unassessed, not zero quality.",'']
    lines += ['## Limits','','Token cost is a usage proxy, not billed dollars. Tokens per supported completion include tokens spent on failed answers; missing usage or zero reviewed successes leaves this ratio unknown and blocks promotion. Both total tokens and this ratio must not increase. One run per profile/question; p95 is effectively the maximum on these small samples. Local timing depends on hardware load and caching. Order is counterbalanced and model warm-up is excluded from answering latency. Split membership and question rubrics are recorded in the manifest. A validation label alone does not establish that cases were unseen; disclose prior inspection and tuning, and any reuse of familiar source fixtures. No automatic rollout or self-modification occurs.','']
    lines += ['## Promotion gate','',str(gate),'']
    if review:lines += ['Reviewer: '+str(result['reviewer']),'']
    (output/'summary.md').write_text('\n'.join(lines)+'\n')


def experiment_cases(cases_file, splits_file):
    cases=load_cases(cases_file)
    splits=json.loads(Path(splits_file).read_text())
    dev_list=splits['development'];val_list=splits['validation']
    if not isinstance(dev_list,list) or not isinstance(val_list,list):
        raise ValueError('Experiment splits must be lists of case IDs')
    dev,val=set(dev_list),set(val_list)
    if len(dev)!=len(dev_list) or len(val)!=len(val_list) or dev & val:
        raise ValueError('Duplicate or overlapping experiment case IDs')
    available={c.id for c in cases}
    if not dev|val or (dev|val)!=available:
        raise ValueError('Splits must assign every supplied case exactly once')
    return cases,dev,val


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--model',default='gemma4:e4b')
    parser.add_argument('--suite',choices=['education','broad'],default='education')
    parser.add_argument('--cases-file',type=Path,help='Custom versioned Case dataset; requires --splits-file')
    parser.add_argument('--splits-file',type=Path,help='Predeclared development/validation case IDs')
    parser.add_argument('--split',choices=['development','validation','all'],default='all')
    parser.add_argument('--max-requests',type=int,default=0)
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--review',type=Path,help='Render completed saved runs with separate reviewer labels; no model calls')
    args=parser.parse_args()
    if bool(args.cases_file)!=bool(args.splits_file):parser.error('--cases-file and --splits-file must be supplied together')
    suite=json.loads(Path(__file__).with_name('efficiency_broad.json').read_text()) if args.suite=='broad' else {'development':list(DEV),'validation':list(VALIDATION)}
    dev,validation=set(suite['development']),set(suite['validation'])
    all_cases=load_cases()
    if args.cases_file:
        try:all_cases,dev,validation=experiment_cases(args.cases_file,args.splits_file)
        except (ValueError,KeyError,TypeError) as error:parser.error(str(error))
    ids=dev if args.split=='development' else validation if args.split=='validation' else dev|validation
    cases=[c for c in all_cases if c.id in ids]
    if not cases:parser.error('The selected split has no cases')
    if args.review:
        summarize(args.output,[json.loads(p.read_text()) for p in sorted(args.output.glob('*-run.json'))],args.review,dev,validation);return
    bound=len(cases)*2*36+1
    print(f'{len(cases)} questions, two full-agent profiles, maximum {bound} local requests including warm-up. No external APIs.',flush=True)
    if args.dry_run:
        for c in cases:print(c.id, 'development' if c.id in dev else 'validation',c.question)
        return
    if args.max_requests<bound:parser.error('Explicit --max-requests must cover the printed bound')
    if args.output.exists() and not args.resume:parser.error('Use a fresh directory or --resume')
    args.output.mkdir(parents=True,exist_ok=args.resume)
    criteria={c.id:CRITERIA[c.id] if args.suite=='education' and not args.cases_file else ' '.join(c.criteria) for c in cases}
    settings={'evaluation_contract':'frozen-evidence-v2','suite':'custom' if args.cases_file else args.suite,'splits':{'development':sorted(dev),'validation':sorted(validation)},'model':args.model,'cases':[c.model_dump() for c in cases],'code_sha256':fingerprint(),'rubric':criteria,'order_seed':42}
    with (args.output/'.run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        path=args.output/'manifest.json'
        if path.exists():
            manifest=json.loads(path.read_text())
            if manifest['settings']!=settings:parser.error('Code/model/rubric changed; use a fresh experiment')
        else:
            manifest={'settings':settings,'state':'running','planned_answers':len(cases)*2,'maximum_requests':bound};write(path,manifest)
        # Warm the same local model before either profile; no tools or source retrieval.
        if 'warmup' not in manifest:
            start=time.monotonic()
            ready=OllamaModel(args.model,SYSTEM).respond('assistant_route',{'question':'What is diversification?','instruction':'Classify the question; do not answer it.'},Route,60)
            manifest['warmup']={'seconds':time.monotonic()-start,'output':ready.model_dump()};write(path,manifest)
        random.Random(42).shuffle(cases)
        for index,case in enumerate(cases):
            profiles=('standard','efficient') if index%2==0 else ('efficient','standard')
            for profile in profiles:
                file=args.output/f'{case.id}-{profile}-run.json'
                if file.exists():continue
                print(f'[{index+1}/{len(cases)}] {case.id}: {profile}',flush=True)
                run=run_case(case,OllamaModel(args.model,SYSTEM),execution_profile=profile,progress=lambda message:print("  "+message,flush=True))
                run['label']=f'{case.id}-{profile}'
                write(file,run)
            summarize(args.output,[json.loads(p.read_text()) for p in sorted(args.output.glob('*-run.json'))],development=dev,validation=validation)
        runs=[json.loads(p.read_text()) for p in sorted(args.output.glob('*-run.json'))]
        template={'reviewer':'','instructions':'Review actual answer text against criteria and collected sources. Do not use self-reported completion. Leave null when unassessed. Preserve hashes.','runs':[{'case_id':r['case_id'],'profile':r['execution_profile'],'answer_sha256':answer_hash(r),'criteria':criteria[r['case_id']],'complete':None,'supported':None,'notes':''} for r in runs]}
        if not (args.output/'review-template.json').exists():write(args.output/'review-template.json',template)
        manifest.update(state='complete',recorded_answers=len(runs));write(path,manifest)
        print('Saved '+str(args.output/'summary.md'),flush=True)


if __name__=='__main__':main()
