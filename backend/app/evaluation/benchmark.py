"""Run the unified assistant or sentiment specialist against a labeled benchmark."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
from statistics import mean, median
import subprocess
from app.evaluation.benchmark_data import load_cases
from app.evaluation.checks import deterministic_metrics, rate
from app.evaluation.compare import write_json
from app.evaluation.recording import run_case
from app.evaluation.judge import judge_run, manual_template, judge_packet, assessment_metrics, SYSTEM as JUDGE_SYSTEM
from app.providers.openrouter import create_model


def fingerprint():
    root=Path(__file__).parents[1]
    return hashlib.sha256(b''.join(str(p.relative_to(root)).encode()+p.read_bytes() for p in sorted(root.rglob('*')) if p.is_file() and p.suffix in ('.py','.json'))).hexdigest()


def aggregate(items,planned=None):
    summary={'planned_runs':planned if planned is not None else len(items),'recorded_runs':len(items),
             'statuses':dict(Counter(i['status'] for i in items)), 'deterministic':{},'llm_judged':{},'manual':{},'categories':{}}
    for method in ('deterministic','llm_judged','manual'):
        metrics=[i.get(method,{}).get('metrics',{}) if method!='deterministic' else i.get(method,{}) for i in items]
        keys={key for row in metrics for key,value in row.items() if isinstance(value,dict) and {'passed','total'}<=value.keys()}
        summary[method]={key:{**rate(sum(row.get(key,{}).get('passed',0) for row in metrics),sum(row.get(key,{}).get('total',0) for row in metrics)),
                              'assessed_runs':sum(row.get(key,{}).get('total',0)>0 for row in metrics)} for key in sorted(keys)}
    summary['reported_completion_rate']=mean(i.get('deterministic',{}).get('reported_completion',False) for i in items) if items else None
    summary['resource_use']={'agent_requests':sum(i['telemetry']['request_budget_used'] for i in items),
        'judge_requests':sum(i.get('llm_judged',{}).get('telemetry',{}).get('request_budget_used',0) for i in items),
        'median_agent_seconds':median(i['latency_seconds'] for i in items) if items else None,
        'mean_agent_seconds':mean(i['latency_seconds'] for i in items) if items else None}
    summary['failures']=[]
    for item in items:
        deterministic=item.get('deterministic',{})
        quality=[]
        for key in ('routing_accuracy','calculation_accuracy','citation_integrity','required_tool_group_coverage'):
            value=deterministic.get(key,{}).get('rate')
            if value is not None and value<1:quality.append(key)
        for method in ('llm_judged','manual'):
            for key,value in item.get(method,{}).get('metrics',{}).items():
                ratio=value.get('rate')
                if ratio is not None and ((key=='unsupported_claim_rate' and ratio>0) or (key!='unsupported_claim_rate' and ratio<1)):
                    quality.append(method+':'+key)
        judge_errors=item.get('llm_judged',{}).get('errors',[])
        if item['status']=='error' or deterministic.get('tool_failures') or deterministic.get('model_failures') or quality or judge_errors:
            summary['failures'].append({'case_id':item['case_id'],'label':item.get('label'),'variant':item.get('variant'),
                'status':item['status'],'errors':item.get('errors',[]),'judge_errors':judge_errors,'quality_flags':quality,
                'tool_failures':deterministic.get('tool_failures',0),'model_failures':deterministic.get('model_failures',0)})
    for category in sorted({i['category'] for i in items}):
        subset=[i for i in items if i['category']==category]
        summary['categories'][category]={'runs':len(subset),'errors':sum(i['status']=='error' for i in subset),
            'llm_task_completion':rate(sum(i.get('llm_judged',{}).get('metrics',{}).get('task_completion',{}).get('passed',0) for i in subset),sum(i.get('llm_judged',{}).get('metrics',{}).get('task_completion',{}).get('total',0) for i in subset))}
    # Paired costs and quality; do not compare unrelated questions or omit failures.
    pairs={}
    for item in items:pairs.setdefault((item['case_id'],item.get('repeat',0)),{})[item.get('variant','enabled')]=item
    summary['paired']=[]
    for (case,repeat),pair in pairs.items():
        if not {'enabled','disabled'}<=pair.keys():continue
        a,b=pair['disabled'],pair['enabled']
        delta={'case_id':case,'repeat':repeat,'extra_requests':b['telemetry']['request_budget_used']-a['telemetry']['request_budget_used'],
               'extra_seconds':b['latency_seconds']-a['latency_seconds'],
               'sentiment_consulted':bool(b['trace'].get('sentiment_results')),'task_completion_delta':None}
        av=a.get('llm_judged',{}).get('metrics',{}).get('task_completion',{}).get('rate')
        bv=b.get('llm_judged',{}).get('metrics',{}).get('task_completion',{}).get('rate')
        if av is not None and bv is not None:delta['task_completion_delta']=bv-av
        summary['paired'].append(delta)
    return summary


def render_summary(summary):
    lines=['# Financial research evaluation','',f"Recorded {summary['recorded_runs']} of {summary['planned_runs']} planned runs.",'',
        'Completion reported by the agent is not independently assessed task completion. Null metrics are unassessed.', '']
    for method in ('deterministic','llm_judged','manual'):
        lines += [f'## {method.replace("_"," ").title()}','', '| Metric | Numerator / assessed | Rate | Assessed runs |','| --- | ---: | ---: | ---: |']
        for key,m in summary[method].items():
            value='Unassessed' if m['rate'] is None else f"{m['rate']:.1%}"
            lines.append(f"| {key} | {m['passed']} / {m['total']} | {value} | {m['assessed_runs']} |")
    lines += ['', 'Unsupported-claim rate is a failure rate: lower is better. Other rates are higher-is-better.',
        'Tool labels are authored expectations. Citation integrity is not entailment. See per-run traces and rubric judgments.',
        '', '## Resource use', '', '```json',json.dumps(summary['resource_use'],indent=2),'```',
        '',f"Runs flagged for quality, errors, missing evidence or incomplete judging: {len(summary['failures'])}.",
        'See summary.json for category breakdowns, failure IDs and paired comparisons.']
    return '\n'.join(lines)+'\n'


def save_summary(output,items,planned):
    summary=aggregate(items,planned);write_json(output/'summary.json',summary)
    (output/'summary.md').write_text(render_summary(summary))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',default='financial_data-01',help='Case ID or all')
    parser.add_argument('--category')
    parser.add_argument('--mode',choices=['frozen','live'],default='frozen')
    parser.add_argument('--target',choices=['assistant','sentiment'],default='assistant')
    parser.add_argument('--sentiment',choices=['enabled','disabled','paired'],default='enabled')
    parser.add_argument('--repeats',type=int,default=1)
    parser.add_argument('--budget',type=int,default=36)
    parser.add_argument('--judge',action='store_true')
    parser.add_argument('--judge-provider',choices=['ollama','openrouter'])
    parser.add_argument('--judge-model')
    parser.add_argument('--judge-budget',type=int,default=12)
    parser.add_argument('--max-requests',type=int,default=72)
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    if not 1<=args.repeats<=3 or not 4<=args.budget<=36 or not 1<=args.judge_budget<=48:parser.error('repeats: 1–3; agent budget: 4–36; judge budget: 1–48')
    cases=[c for c in load_cases() if (args.case=='all' or c.id==args.case) and (not args.category or c.category==args.category)]
    if args.target=='sentiment':cases=[c for c in cases if c.sentiment_target]
    if not cases:parser.error('No matching cases; use --case all when selecting a category or sentiment target')
    if args.mode=='live' and any(c.scenario!='normal' for c in cases):parser.error('Live runs cannot reproduce frozen failure scenarios; choose normal cases')
    variants=['disabled','enabled'] if args.sentiment=='paired' else [args.sentiment]
    if args.target=='sentiment' and args.sentiment!='enabled':parser.error('Direct sentiment target requires --sentiment enabled')
    tasks=[(c,r,v) for c in cases for r in range(args.repeats) for v in variants];random.Random(args.seed).shuffle(tasks)
    bound=len(tasks)*(args.budget+(args.judge_budget if args.judge else 0))
    print(f'{len(tasks)} runs, maximum {bound} model requests including retries and judges. Mode: {args.mode}.')
    if args.dry_run:return
    if bound>args.max_requests:parser.error('Request ceiling exceeded; reduce scope or explicitly raise --max-requests')
    if args.output.exists():parser.error('Output already exists; choose a new directory')
    args.output.mkdir(parents=True)
    try:revision=subprocess.check_output(['git','rev-parse','HEAD'],text=True,stderr=subprocess.DEVNULL).strip()
    except (OSError,subprocess.CalledProcessError):revision=None
    manifest={'version':'1.0','created_at':datetime.now(timezone.utc).isoformat(),'code_and_data_sha256':fingerprint(),'git_revision':revision,
              'provider':os.getenv('LLM_PROVIDER','ollama'),'options':{k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()},
              'planned_runs':len(tasks),'request_upper_bound':bound,'cases':[c.model_dump() for c in cases],
              'label_provenance':'Authored benchmark labels; not independently annotated by financial experts.'}
    write_json(args.output/'manifest.json',manifest);items=[]
    write_json(args.output/'index.json',[])
    save_summary(args.output,items,len(tasks))
    for index,(case,repeat,variant) in enumerate(tasks):
        label=f'{index+1:03}-{case.id}-{variant}-r{repeat+1}'
        try:
            base=create_model()
            run=run_case(case,base,args.budget,args.mode,variant=='enabled',args.target)
        except Exception as error:
            run={'case_id':case.id,'category':case.category,'question':case.question,'target':args.target,'mode':args.mode,
                 'as_of':datetime.now(timezone.utc).date().isoformat(),'status':'error','workflow':None,'report':None,
                 'errors':[{'type':type(error).__name__}],'telemetry':{'request_budget_used':0,'calls':[]},'latency_seconds':0,
                 'investigation_iterations':{'research':0,'investment':0,'sentiment':0},
                 'trace':{'model_decisions':[],'tool_calls':[],'articles':{},'sentiment_results':[]}}
        run.update(label=label,repeat=repeat,variant=variant)
        run['deterministic']=deterministic_metrics(case,run)
        write_json(args.output/(label+'.json'),run) # Persist agent result before any optional judge.
        write_json(args.output/(label+'.review.json'),manual_template(case,run))
        if args.judge:
            try:
                from unittest.mock import patch
                provider=args.judge_provider or os.getenv('LLM_PROVIDER','ollama')
                with patch.dict(os.environ,{'LLM_PROVIDER':provider}):judge=create_model(args.judge_model,system_prompt=JUDGE_SYSTEM)
                run['llm_judged']=judge_run(case,run,judge,args.judge_budget)
            except Exception as error:run['llm_judged']={'method':'llm_judged','errors':[{'type':type(error).__name__}],'metrics':{}}
        items.append(run);write_json(args.output/(label+'.json'),run)
        write_json(args.output/'index.json',[{'label':i['label'],'case_id':i['case_id'],'status':i['status']} for i in items])
        save_summary(args.output,items,len(tasks))
        print(label,run['status'],f"agent requests={run['telemetry']['request_budget_used']}",flush=True)
    print('Review summary.md and individual *.json traces. No unjudged quality score is assumed to pass.')


if __name__=='__main__':main()
