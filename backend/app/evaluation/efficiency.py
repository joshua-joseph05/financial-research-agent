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
    return hashlib.sha256(json.dumps(run.get('report'),sort_keys=True).encode()).hexdigest()


def summarize(output,runs,review=None):
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
    for split,ids in [('development',DEV),('validation',VALIDATION),('all',DEV|VALIDATION)]:
        paired=[key for key in sorted(ids) if all((key,s) in labels for s in ('standard','efficient'))]
        assessed=[key for key in paired if all(checks.get((key,s),{}).get('complete') is not None and checks.get((key,s),{}).get('supported') is not None for s in ('standard','efficient'))]
        rows[split]={'paired_questions':len(paired),'reviewed_pairs':len(assessed),'profiles':{}}
        for profile in ('standard','efficient'):
            samples=[labels[(key,profile)] for key in paired];latencies=sorted(r['latency_seconds'] for r in samples)
            known_tokens=[r['telemetry'].get('tokens',{}).get('total_tokens') for r in samples]
            rows[split]['profiles'][profile]={
                'mean_model_calls':mean(r['telemetry']['model_calls'] for r in samples) if samples else None,
                'mean_latency_seconds':mean(latencies) if latencies else None,
                'median_latency_seconds':median(latencies) if latencies else None,
                'p95_latency_seconds':latencies[math.ceil(.95*len(latencies))-1] if latencies else None,
                'mean_total_tokens':mean(t for t in known_tokens if t is not None) if any(t is not None for t in known_tokens) else None,
                'token_coverage':sum(t is not None for t in known_tokens),
                'errors':sum(r['status']=='error' for r in samples),
                'reviewed_completion':sum(checks[(key,profile)]['complete'] for key in assessed),
                'reviewed_supported_answers':sum(checks[(key,profile)]['supported'] for key in assessed)}
    validation=rows['validation']
    if validation['reviewed_pairs']!=len(VALIDATION):
        gate={'status':'awaiting_validation_review','reason':'All five reserved validation pairs need separate completion and factual-support review.'}
    else:
        a,b=[validation['profiles'][p] for p in ('standard','efficient')]
        quality=(b['reviewed_completion']>=a['reviewed_completion'] and b['reviewed_supported_answers']==len(VALIDATION) and b['errors']==0)
        efficient=(b['mean_model_calls']<a['mean_model_calls'] and b['median_latency_seconds']<a['median_latency_seconds'] and b['p95_latency_seconds']<=a['p95_latency_seconds'])
        gate={'status':'promising_small_sample' if quality and efficient else 'do_not_promote',
              'quality_nonregression':quality,'measured_efficiency_gain':efficient,
              'reason':'No automatic rollout. Validate additional cases and repeated timing runs before broader use.'}
    result={'comparison':'Both agents collect their own evidence; same model, frozen sources and questions. No inherited-evidence baseline.','metrics':rows,'gate':gate,'reviewer':json.loads(review.read_text()).get('reviewer') if review else None}
    write(output/'summary.json',result)
    lines=['# Agent efficiency experiment','','Both profiles retrieve evidence and retain source review. The standard profile is the unchanged reference path; efficient is opt-in.','',
           'Quality is unassessed until a separate reviewer supplies completion and support decisions against the predeclared rubric. The agent’s own complete flag is not a quality score.','']
    for split,row in rows.items():
        lines += [f"## {split}: {row['paired_questions']} paired questions",'', '| Measure | Standard | Efficient |','| --- | ---: | ---: |']
        for key in row['profiles']['standard']:
            lines.append(f"| {key} | {row['profiles']['standard'][key]} | {row['profiles']['efficient'][key]} |")
        lines += ['',f"Quality denominator: {row['reviewed_pairs']} jointly reviewed pairs. Zero reviewed successes with zero assessed pairs means unassessed, not zero quality.",'']
    lines += ['## Limits','','One run per profile/question; p95 is effectively the maximum on these small samples. Local timing depends on hardware load and caching. Order is counterbalanced and model warm-up is excluded from answering latency. Validation cases were reserved before this change was tested, but belong to the existing public benchmark, not a wholly unseen corpus. No automatic rollout or self-modification occurs.','']
    lines += ['## Promotion gate','',str(gate),'']
    if review:lines += ['Reviewer: '+str(result['reviewer']),'']
    (output/'summary.md').write_text('\n'.join(lines)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--model',default='gemma4:e4b')
    parser.add_argument('--split',choices=['development','validation','all'],default='all')
    parser.add_argument('--max-requests',type=int,default=0)
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--review',type=Path,help='Render completed saved runs with separate reviewer labels; no model calls')
    args=parser.parse_args()
    ids=DEV if args.split=='development' else VALIDATION if args.split=='validation' else DEV|VALIDATION
    cases=[c for c in load_cases() if c.id in ids]
    if args.review:
        summarize(args.output,[json.loads(p.read_text()) for p in sorted(args.output.glob('*-run.json'))],args.review);return
    bound=len(cases)*2*36+1
    print(f'{len(cases)} questions, two full-agent profiles, maximum {bound} local requests including warm-up. No external APIs.',flush=True)
    if args.dry_run:
        for c in cases:print(c.id, 'development' if c.id in DEV else 'validation',c.question)
        return
    if args.max_requests<bound:parser.error('Explicit --max-requests must cover the printed bound')
    if args.output.exists() and not args.resume:parser.error('Use a fresh directory or --resume')
    args.output.mkdir(parents=True,exist_ok=args.resume)
    settings={'model':args.model,'cases':[c.model_dump() for c in cases],'code_sha256':fingerprint(),'rubric':CRITERIA,'order_seed':42}
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
                run=run_case(case,OllamaModel(args.model,SYSTEM),execution_profile=profile)
                run['label']=f'{case.id}-{profile}'
                write(file,run)
            summarize(args.output,[json.loads(p.read_text()) for p in sorted(args.output.glob('*-run.json'))])
        runs=[json.loads(p.read_text()) for p in sorted(args.output.glob('*-run.json'))]
        template={'reviewer':'','instructions':'Review actual answer text against criteria and collected sources. Do not use self-reported completion. Leave null when unassessed. Preserve hashes.','runs':[{'case_id':r['case_id'],'profile':r['execution_profile'],'answer_sha256':answer_hash(r),'criteria':CRITERIA[r['case_id']],'complete':None,'supported':None,'notes':''} for r in runs]}
        if not (args.output/'review-template.json').exists():write(args.output/'review-template.json',template)
        manifest.update(state='complete',recorded_answers=len(runs));write(path,manifest)
        print('Saved '+str(args.output/'summary.md'),flush=True)


if __name__=='__main__':main()
