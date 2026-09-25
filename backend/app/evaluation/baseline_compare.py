"""Compare saved full-agent runs with a same-model single-pass evidence baseline."""
import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime,timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import time
from unittest.mock import patch
from app.evaluation.baseline import run_baseline,evidence_bundle,answer_calculations,SYSTEM as BASELINE_SYSTEM
from app.evaluation.baseline_report import comparison_summary,render
from app.evaluation.benchmark_data import Case
from app.evaluation.benchmark import fingerprint
from app.evaluation.compare import write_json
from app.evaluation.judge import judge_run,SYSTEM as JUDGE_SYSTEM
from app.providers.openrouter import create_model


@contextmanager
def source_lock(directory,wait=False,notify=print):
    """Do not compete for inference with the source evaluation."""
    with (directory/'.run.lock').open('a') as handle:
        while True:
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB);break
            except BlockingIOError:
                if not wait:raise ValueError('Source evaluation is running; use --wait or return when it finishes')
                try:
                    summary=json.loads((directory/'summary.json').read_text())
                    notify(f"Waiting for source evaluation: {summary['recorded_runs']}/{summary['planned_runs']} answers saved. No baseline requests made.")
                except (OSError,ValueError,KeyError):notify('Waiting for active source evaluation. No baseline requests made.')
                time.sleep(30)
        try:yield
        finally:fcntl.flock(handle,fcntl.LOCK_UN)


def load_agent_runs(directory,manifest,allow_partial=False):
    index=json.loads((directory/'index.json').read_text())
    if len(index)!=manifest['planned_runs'] and not allow_partial:
        raise ValueError('Source evaluation ended before all planned runs were recorded; resume it or explicitly use --allow-partial')
    runs=[]
    for row in index:
        run=json.loads((directory/(row['label']+'.json')).read_text())
        if run.get('target')!='assistant':raise ValueError('Comparison requires unified assistant runs, not direct specialist runs')
        if not run.get('model',{}).get('name'):
            # Without identity there is no way to guarantee the same underlying model.
            raise ValueError('A source run lacks a model identity: '+row['label'])
        runs.append(run)
    if len({r['label'] for r in runs})!=len(runs):raise ValueError('Duplicate source run labels')
    return runs


def compare_pair(case,agent,base_model,judge_factory,baseline_budget=2,judge_budget=12,seed=42,progress=None,cached=None,save=None):
    progress=progress or (lambda text:None)
    bundle,digest=evidence_bundle(agent)
    pair=cached or {'id':agent['label']+'-comparison','case_id':case.id,'category':case.category,'question':case.question,
                   'agent':agent,'evidence_bundle_sha256':digest,'judgments':{}}
    if pair['evidence_bundle_sha256']!=digest:raise ValueError('Agent evidence changed; use a new comparison directory')
    if 'baseline' not in pair:
        pair['baseline']=run_baseline(agent,base_model,baseline_budget,progress)
        if save:save(pair)
    order=['agent','baseline'];random.Random(str(seed)+pair['id']).shuffle(order)
    pair['judge_order']=order
    for system in order:
        if system in pair['judgments']:continue
        progress('Assessing anonymous answer '+str(order.index(system)+1)+' of 2')
        try:
            pair['judgments'][system]=judge_run(case,pair[system],judge_factory(),judge_budget,progress,
                                               answer_only=True,shared_evidence=bundle['evidence'])
        except Exception as error:
            pair['judgments'][system]={'method':'llm_judged','rubric_version':'comparison-answer-only-v1','errors':[{'type':type(error).__name__}],'metrics':{}}
        if save:save(pair)
    pair['calculations']={system:answer_calculations(pair[system]) for system in ('agent','baseline')}
    if save:save(pair)
    return pair


def save_report(output,pairs,categories):
    summary=comparison_summary(pairs,categories)
    write_json(output/'comparison.json',summary)
    (output/'comparison.md').write_text(render(summary))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agent-directory',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline-budget',type=int,default=2)
    parser.add_argument('--judge-budget',type=int,default=12)
    parser.add_argument('--judge-provider',choices=['ollama','openrouter'])
    parser.add_argument('--judge-model')
    parser.add_argument('--max-requests',type=int,default=72)
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--wait',action='store_true')
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--allow-partial',action='store_true')
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    if not 1<=args.baseline_budget<=4 or not 1<=args.judge_budget<=48:parser.error('Baseline budget 1–4; judge budget 1–48')
    original=json.loads((args.agent_directory/'manifest.json').read_text())
    planned=original['planned_runs'];bound=planned*(args.baseline_budget+2*args.judge_budget)
    print(f'{planned} planned pairs; at most {bound} additional model requests (baseline plus two fresh judges).',flush=True)
    if args.dry_run:return
    if bound>args.max_requests:parser.error('Raise --max-requests explicitly or use a smaller source experiment')
    if args.output.exists() and not args.resume:parser.error('Output exists; use a new directory or --resume')
    args.output.mkdir(parents=True,exist_ok=args.resume)
    with (args.output/'.run.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:parser.error('Comparison already running')
        cases={c['id']:Case.model_validate(c) for c in original['cases']}
        repeats=original['options']['repeats'];variants=2 if original['options']['sentiment']=='paired' else 1
        categories={category:n*repeats*variants for category,n in Counter(c.category for c in cases.values()).items()}
        settings={k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items() if k not in ('wait','resume','dry_run','max_requests')}
        path=args.output/'manifest.json'
        if path.exists():
            manifest=json.loads(path.read_text())
            if manifest['settings']!=settings:parser.error('Resume settings must match the original comparison')
        else:
            manifest={'protocol':'same-evidence-single-pass-v1','created_at':datetime.now(timezone.utc).isoformat(),
                      'settings':settings,'planned_pairs':planned,'request_upper_bound':bound,'code_sha256':fingerprint(),
                      'source_manifest':original,'state':'waiting_for_source'}
            write_json(path,manifest)
        pairs=[json.loads(p.read_text()) for p in sorted(args.output.glob('*-comparison.json')) if 'calculations' in json.loads(p.read_text())]
        save_report(args.output,pairs,categories)
        with source_lock(args.agent_directory,args.wait,lambda message:print(message,flush=True)):
            agents=load_agent_runs(args.agent_directory,original,args.allow_partial)
            # Take a private snapshot while holding the source lock. No writes to source artifacts.
            manifest.update(state='running',source_runs_available=len(agents))
            write_json(path,manifest)
            random.Random(args.seed).shuffle(agents)
            for index,agent in enumerate(agents):
                label=agent['label']+'-comparison';target=args.output/(label+'.json')
                cached=json.loads(target.read_text()) if target.exists() else None
                def progress(message):print(f'[{index+1}/{len(agents)}] {agent["case_id"]}: {message}',flush=True)
                provider=original['provider']
                with patch.dict(os.environ,{'LLM_PROVIDER':provider}):
                    baseline_model=create_model(agent['model']['name'],system_prompt=BASELINE_SYSTEM)
                if type(baseline_model).__name__!=agent['model']['class']:raise ValueError('Baseline provider class differs from source agent')
                def judge_factory():
                    with patch.dict(os.environ,{'LLM_PROVIDER':args.judge_provider or provider}):
                        return create_model(args.judge_model or agent['model']['name'],system_prompt=JUDGE_SYSTEM)
                pair=compare_pair(cases[agent['case_id']],agent,baseline_model,judge_factory,args.baseline_budget,args.judge_budget,args.seed,progress,cached,lambda value:write_json(target,value))
                pairs=[p for p in pairs if p['id']!=pair['id']]+[pair];save_report(args.output,pairs,categories)
                progress('Pair saved')
        manifest['state']='complete' if len(pairs)==planned else 'partial'
        manifest['finished_at']=datetime.now(timezone.utc).isoformat();write_json(path,manifest)
        print('Comparison report saved to '+str(args.output/'comparison.md'),flush=True)


if __name__=='__main__':main()
