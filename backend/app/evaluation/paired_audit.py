"""Offline, per-question audit of a completed paired experiment; no inference."""
import argparse
from copy import deepcopy
import json
import hashlib
import math
from pathlib import Path
import random
from app.evaluation.efficiency import answer_hash

PROFILES=('standard','efficient')


def number(value):
    return value if type(value) in (int,float) and math.isfinite(value) and value>=0 else None


def reduction(before,after):
    return 100*(before-after)/before if before is not None and before>0 and after is not None else None


def index_runs(runs,expected):
    if not expected:raise ValueError('The experiment has no questions')
    indexed={}
    for run in runs:
        key=(run['case_id'],run['execution_profile'])
        if key in indexed:raise ValueError('Duplicate case/profile run')
        if key[0] not in expected or key[1] not in PROFILES:raise ValueError('Unknown case or profile')
        indexed[key]=run
    if set(indexed)!={(case,p) for case in expected for p in PROFILES}:
        raise ValueError('The experiment must have every expected pair; incomplete runs cannot be silently dropped')
    for case in expected:
        if indexed[(case,'standard')]['question']!=indexed[(case,'efficient')]['question']:
            raise ValueError('Paired question text differs')
    return indexed


def experiment_hash(manifest):
    return hashlib.sha256(json.dumps(manifest['settings'],sort_keys=True).encode()).hexdigest()


def indexed_experiment(runs,manifest):
    cases=manifest['settings']['cases'];expected={c['id'] for c in cases}
    if len(cases)!=len(expected):raise ValueError('Duplicate manifest case')
    indexed=index_runs(runs,expected)
    for case in cases:
        for profile in PROFILES:
            if indexed[(case['id'],profile)]['question']!=case['question']:raise ValueError('Run question differs from predeclared manifest')
    return expected,indexed


def audit(runs,review,manifest):
    expected,indexed=indexed_experiment(runs,manifest)
    checked={}
    for item in review['runs']:
        key=(item['case_id'],item['profile'])
        if key not in indexed or key in checked:raise ValueError('Unknown or duplicate review')
        if item['answer_sha256']!=answer_hash(indexed[key]):raise ValueError('Stale review hash')
        if any(type(item.get(k)) is not bool for k in ('complete','supported')):raise ValueError('Every answer must be reviewed')
        checked[key]=item
    if checked.keys()!=indexed.keys():raise ValueError('Missing reviews')
    cases=[]
    for case in sorted(expected):
        row={'case_id':case,'question':indexed[(case,'standard')]['question'],'category':indexed[(case,'standard')]['category'],'profiles':{}}
        for profile in PROFILES:
            run=indexed[(case,profile)];rating=checked[(case,profile)]
            row['profiles'][profile]={'complete':rating['complete'],'supported':rating['supported'],'success':rating['complete'] and rating['supported'],
                'calls':number(run['telemetry'].get('model_calls')),'seconds':number(run.get('latency_seconds')),
                'tokens':number(run['telemetry'].get('tokens',{}).get('total_tokens')),'notes':rating.get('notes','')}
        a,b=[row['profiles'][p] for p in PROFILES]
        row['reductions_percent']={k:reduction(a[k],b[k]) for k in ('calls','seconds','tokens')}
        row['quality_regressions']=[k for k in ('complete','supported') if a[k] and not b[k]]
        row['efficiency_regressions']=[k for k in ('calls','seconds','tokens') if a[k] is not None and b[k] is not None and b[k]>a[k]]
        row['candidate_failure']=not b['success']
        cases.append(row)
    both_success=[row for row in cases if all(row['profiles'][p]['success'] for p in PROFILES)]
    def totals(rows):
        result={}
        for metric in ('calls','seconds','tokens'):
            values={p:[r['profiles'][p][metric] for r in rows] for p in PROFILES}
            sums={p:sum(v) if v and all(x is not None for x in v) else None for p,v in values.items()}
            result[metric]={**sums,'reduction_percent':reduction(sums['standard'],sums['efficient'])}
        return result
    return {'reviewer':review.get('reviewer'),'questions':len(cases),'all_attempts':totals(cases),
        'successful_in_both':{'questions':len(both_success),'metrics':totals(both_success)},
        'quality_counts':{p:{k:sum(r['profiles'][p][k] for r in cases) for k in ('complete','supported','success')} for p in PROFILES},
        'cases':cases,'limits':'New versus familiar questions and reviewer independence must be established separately. One observation per question does not measure timing stability. Speed on failed answers is included in all_attempts, not treated as successful task efficiency. Zero jointly successful pairs means successful-task speed comparison is unavailable.'}


def review_packet(runs,manifest,seed=42):
    expected,indexed=indexed_experiment(runs,manifest)
    rng=random.Random(seed);cases=[];mapping=[]
    for case in sorted(expected):
        order=list(PROFILES);rng.shuffle(order);answers=[]
        for slot,profile in zip(('A','B'),order):
            run=indexed[(case,profile)]
            report=deepcopy(run.get('report'))
            if report:
                for key in ('telemetry','tool_calls','as_of'):report.pop(key,None)
            answers.append({'slot':slot,'report':report,'clarification':run.get('clarification'),'errors':run.get('errors',[])})
            mapping.append({'case_id':case,'slot':slot,'profile':profile,'answer_sha256':answer_hash(run)})
        cases.append({'case_id':case,'question':indexed[(case,'standard')]['question'],'criteria':manifest['settings']['rubric'][case],'answers':answers})
    packet={'instructions':'Score completion and support separately against the criteria and each claim’s own citations. Correct numbers with missing requested explanation may be incomplete. Correct requested content plus extra unsupported claims fails support. A clearly explained, justified limitation may satisfy a qualified-answer rubric. Do not use self-reported complete/verified flags as scores. Version names and performance metrics are hidden, but formatting may reveal implementation differences; blinding is partial. Do not open the private mapping before scoring.', 'cases':cases}
    scores={'reviewer':'','runs':[{'case_id':m['case_id'],'slot':m['slot'],'complete':None,'supported':None,'notes':''} for m in mapping]}
    return packet,{'experiment_sha256':experiment_hash(manifest),'mapping':mapping},scores



def import_scores(runs,manifest,mapping,scores):
    expected,indexed=indexed_experiment(runs,manifest)
    if mapping.get('experiment_sha256')!=experiment_hash(manifest):raise ValueError('Experiment settings or rubric changed after packet creation')
    if not scores.get('reviewer','').strip():raise ValueError('Name the reviewer and review method')
    slots={};profiles=set()
    for item in mapping['mapping']:
        slot=(item['case_id'],item['slot']);key=(item['case_id'],item['profile'])
        if item['slot'] not in ('A','B') or slot in slots or key in profiles or key not in indexed:raise ValueError('Invalid or duplicate mapping')
        if item['answer_sha256']!=answer_hash(indexed[key]):raise ValueError('Mapping does not match saved answer')
        slots[slot]=item;profiles.add(key)
    if profiles!=set(indexed):raise ValueError('Incomplete mapping')
    reviewed=[];seen=set()
    for item in scores['runs']:
        slot=(item['case_id'],item['slot'])
        if slot not in slots or slot in seen:raise ValueError('Unknown or duplicate scored slot')
        if any(type(item.get(k)) is not bool for k in ('complete','supported')):raise ValueError('All scores must be booleans, not unreviewed placeholders')
        seen.add(slot);identity=slots[slot]
        reviewed.append({'case_id':identity['case_id'],'profile':identity['profile'],'answer_sha256':identity['answer_sha256'],
            'criteria':manifest['settings']['rubric'][identity['case_id']],**{k:item.get(k,'') for k in ('complete','supported','notes')}})
    if seen!=set(slots):raise ValueError('Missing scored slots')
    return {'reviewer':scores['reviewer'],'runs':reviewed}


def render(result):
    def show(value):
        return 'unavailable' if value is None else str(value) if type(value) is int else f'{value:.2f}'
    lines=['# Paired evaluation audit','',f"Reviewed questions: {result['questions']}. Reviewer: {result['reviewer']}",'',
           '| Quality | Standard | Efficient |','|---|---:|---:|']
    for key in ('complete','supported','success'):lines.append(f"| {key} | {result['quality_counts']['standard'][key]} | {result['quality_counts']['efficient'][key]} |")
    lines+=['','Success means both complete and fully source-supported.','', '| All attempts | Standard total | Efficient total | Reduction |','|---|---:|---:|---:|']
    for metric,row in result['all_attempts'].items():
        pct='unavailable' if row['reduction_percent'] is None else f"{row['reduction_percent']:.1f}%"
        lines.append(f"| {metric} | {show(row['standard'])} | {show(row['efficient'])} | {pct} |")
    lines+=['',f"Questions successful in both versions: **{result['successful_in_both']['questions']}**. Compare speed on that matched-success subset separately; do not imply that faster failures are faster completed research.",'']
    if result['successful_in_both']['questions']:
        lines+=['| Matched successful attempts | Standard total | Efficient total | Reduction |','|---|---:|---:|---:|']
        for metric,row in result['successful_in_both']['metrics'].items():
            pct='unavailable' if row['reduction_percent'] is None else f"{row['reduction_percent']:.1f}%"
            lines.append(f"| {metric} | {show(row['standard'])} | {show(row['efficient'])} | {pct} |")
        lines.append('')
    lines += ['## Per-question findings', '']
    for row in result['cases']:
        lines += [f"### {row['case_id']}",'',row['question'],'',f"Candidate failed joint completion/support: {row['candidate_failure']}. Quality regressions: {', '.join(row['quality_regressions']) or 'none'}. Efficiency regressions: {', '.join(row['efficiency_regressions']) or 'none'}.",'']
        for p in PROFILES:
            r=row['profiles'][p]
            lines += [f"- **{p}** — complete={r['complete']}, supported={r['supported']}; {r['calls']} calls, {r['seconds']} seconds, {r['tokens']} tokens. {r['notes']}"]
        lines.append('')
    lines+=['## Limits','',result['limits'],'']
    return '\n'.join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path);parser.add_argument('--review',type=Path)
    parser.add_argument('--scores',type=Path);parser.add_argument('--mapping',type=Path)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--packet',action='store_true')
    args=parser.parse_args()
    if sum((bool(args.packet),bool(args.review),bool(args.scores)))!=1:parser.error('Choose exactly one of --review, --packet, or --scores')
    if bool(args.scores)!=bool(args.mapping):parser.error('--scores and --mapping must be supplied together')
    if args.output.exists():parser.error('Use a new output directory to preserve previous artifacts')
    manifest=json.loads((args.folder/'manifest.json').read_text())
    runs=[json.loads(p.read_text()) for p in sorted(args.folder.glob('*-run.json'))]
    if args.packet:
        packet,mapping,scores=review_packet(runs,manifest)
        outputs={'review-packet.json':packet,'private-mapping.json':mapping,'scores-template.json':scores}
    elif args.scores:
        review=import_scores(runs,manifest,json.loads(args.mapping.read_text()),json.loads(args.scores.read_text()))
        outputs={'review.json':review}
    else:
        result=audit(runs,json.loads(args.review.read_text()),manifest)
        outputs={'paired-audit.json':result,'paired-audit.md':render(result)}
    args.output.mkdir(parents=True)
    for name,value in outputs.items():
        (args.output/name).write_text(value if isinstance(value,str) else json.dumps(value,indent=2)+'\n')
    print(args.output)

if __name__=='__main__':main()
