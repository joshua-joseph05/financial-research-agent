#!/usr/bin/env python3
"""Report token expenditure per reviewed success. Reads saved runs; no inference."""
import argparse
import hashlib
import json
from pathlib import Path


def answer_hash(run):
    answer=run.get('report')
    if answer is None:
        answer={key:run.get(key) for key in ('status','clarification','errors')}
    return hashlib.sha256(json.dumps(answer,sort_keys=True).encode()).hexdigest()


def calculate(runs, review):
    labels={(r['case_id'],r['execution_profile']):r for r in runs}
    if len(labels)!=len(runs):raise ValueError('Duplicate run')
    groups={p:{k for k,profile in labels if profile==p} for p in ('standard','efficient')}
    if not groups['standard'] or groups['standard']!=groups['efficient']:
        raise ValueError('Both profiles need the same complete set of questions')
    checked={}
    for item in review['runs']:
        key=(item['case_id'],item['profile'])
        if key in checked or key not in labels:raise ValueError('Unknown or duplicate review')
        if item['answer_sha256']!=answer_hash(labels[key]):raise ValueError('Review answer hash mismatch')
        if any(type(item.get(k)) is not bool for k in ('complete','supported')):
            raise ValueError('Every answer needs completion and source-support review')
        checked[key]=item
    if checked.keys()!=labels.keys():raise ValueError('Missing answer reviews')
    output={'definition':'A success passes both manual completion and source-support review. Cost includes tokens spent on failed attempts. Token counts are model-specific, not dollar prices.','profiles':{}}
    for profile in groups:
        selected=[r for r in runs if r['execution_profile']==profile]
        success=sum(checked[(r['case_id'],profile)]['complete'] and checked[(r['case_id'],profile)]['supported'] for r in selected)
        known=[r for r in selected if all(type(r['telemetry'].get('tokens',{}).get(k)) is int and r['telemetry']['tokens'][k]>=0 for k in ('prompt_tokens','completion_tokens'))]
        totals={k:sum(r['telemetry']['tokens'][k] for r in known) for k in ('prompt_tokens','completion_tokens')}
        complete_usage=len(known)==len(selected)
        all_tokens=sum(totals.values()) if complete_usage else None
        output['profiles'][profile]={'attempts':len(selected),'reviewed_successes':success,'runs_with_complete_usage':len(known),'known_input_tokens':totals['prompt_tokens'],'known_output_tokens':totals['completion_tokens'],'total_tokens':all_tokens,'tokens_per_attempt':all_tokens/len(selected) if complete_usage else None,'tokens_per_success_including_failures':all_tokens/success if complete_usage and success else None}
    a,b=(output['profiles'][p]['tokens_per_success_including_failures'] for p in ('standard','efficient'))
    output['token_cost_per_success_reduction_percent']=100*(a-b)/a if a and b is not None else None
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path)
    parser.add_argument('--review',type=Path,required=True)
    args=parser.parse_args()
    results=calculate([json.loads(p.read_text()) for p in sorted(args.folder.glob('*-run.json'))],json.loads(args.review.read_text()))
    path=args.folder/'token-cost.json';path.write_text(json.dumps(results,indent=2)+'\n');print(path)
