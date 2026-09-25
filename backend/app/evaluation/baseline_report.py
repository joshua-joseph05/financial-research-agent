"""Matched-pair statistics without a hand-picked composite score."""
from statistics import mean
from app.evaluation.checks import rate

QUALITY=('task_completion','citation_correctness','calculation_accuracy','unsupported_claim_rate')
RESOURCES=('latency_seconds','model_calls','model_requests','tool_calls')

def measures(pair,system):
    run=pair[system];judged=pair.get('judgments',{}).get(system,{})
    metrics=judged.get('metrics',{})
    coverage=metrics.get('claim_assessment_coverage',{}).get('rate')
    # Do not compare partial claim judgments as though they covered the whole answer.
    values={
        'task_completion':metrics.get('task_completion',{}).get('rate'),
        'citation_correctness':metrics.get('citation_support',{}).get('rate') if coverage==1 else None,
        'unsupported_claim_rate':metrics.get('unsupported_claim_rate',{}).get('rate') if coverage==1 else None,
        'calculation_accuracy':pair.get('calculations',{}).get(system,{}).get('metric',{}).get('rate'),
        'latency_seconds':run['latency_seconds'],
        'model_calls':run['telemetry'].get('model_calls',len(run['telemetry'].get('calls',[]))),
        'model_requests':run['telemetry']['request_budget_used'],
        'tool_calls':len(run['trace']['tool_calls'])+len(run['trace'].get('sentiment_results',[])),
    }
    return values


def comparison_metrics(pairs):
    output={}
    for key in QUALITY+RESOURCES:
        values=[(measures(p,'agent')[key],measures(p,'baseline')[key]) for p in pairs]
        matched=[(a,b) for a,b in values if a is not None and b is not None]
        output[key]={'agent_mean':mean(a for a,b in matched) if matched else None,
                     'baseline_mean':mean(b for a,b in matched) if matched else None,
                     'agent_minus_baseline':mean(a-b for a,b in matched) if matched else None,
                     'paired_cases':len(matched),'missing_pairs':len(pairs)-len(matched)}
    return output


def outcome(pair):
    a,b=measures(pair,'agent'),measures(pair,'baseline')
    deltas={k:a[k]-b[k] for k in QUALITY if a[k] is not None and b[k] is not None}
    # Completion must be assessed on both sides before assigning an outcome.
    if 'task_completion' not in deltas:return 'unassessed',deltas
    oriented=[-v if k=='unsupported_claim_rate' else v for k,v in deltas.items()]
    positive=any(v>1e-9 for v in oriented);negative=any(v< -1e-9 for v in oriented)
    if positive and negative:return 'mixed',deltas
    if positive:return 'agent_improves',deltas
    if negative:return 'agent_worse',deltas
    return 'no_measured_quality_gain',deltas


def comparison_summary(pairs,planned_categories):
    planned=sum(planned_categories.values())
    groups={k:[] for k in ('agent_improves','agent_worse','mixed','no_measured_quality_gain','unassessed')}
    details=[]
    for pair in pairs:
        status,deltas=outcome(pair)
        item={'id':pair['id'],'case_id':pair['case_id'],'category':pair['category'],'question':pair['question'],
              'outcome':status,'quality_deltas':deltas,'agent':measures(pair,'agent'),'baseline':measures(pair,'baseline'),
              'artifact':pair['id']+'.json',
              'explanation':'Outcome uses only jointly assessed metrics; a tie is not proof of equivalent quality.'}
        groups[status].append(item);details.append(item)
    return {'protocol':'same-evidence-single-pass-v1','planned_pairs':planned,'recorded_pairs':len(pairs),
            'scope':'Partial' if len(pairs)<planned else 'All planned pairs recorded; inspect assessment coverage',
            'metrics':comparison_metrics(pairs),
            'categories':{cat:{'planned':n,'recorded':sum(p['category']==cat for p in pairs),
                              'metrics':comparison_metrics([p for p in pairs if p['category']==cat])} for cat,n in planned_categories.items()},
            'outcome_counts':{k:len(v) for k,v in groups.items()},'examples':{k:v[:5] for k,v in groups.items()},
            'pairs':details,
            'failures':[{'id':p['id'],'agent_status':p['agent']['status'],'baseline_status':p['baseline']['status'],
                         'judge_errors':{s:p.get('judgments',{}).get(s,{}).get('errors',[]) for s in ('agent','baseline')}}
                        for p in pairs if p['agent']['status']=='error' or p['baseline']['status']=='error' or any(p.get('judgments',{}).get(s,{}).get('errors') for s in ('agent','baseline'))],
            'resource_caveat':'Baseline latency is answer-only with inherited evidence. Agent latency includes retrieval and verification. These are not equivalent end-to-end costs.',
            'shared_preparation':[{'id':p['id'],**p['baseline'].get('shared_preparation',{})} for p in pairs]}


def render(summary):
    def number(value):return 'Unassessed' if value is None else f'{value:.3f}'
    def table(metrics):
        rows=['| Metric | Full agent | Single pass | Agent − baseline | Matched pairs |','| --- | ---: | ---: | ---: | ---: |']
        for key,value in metrics.items():rows.append(f"| {key} | {number(value['agent_mean'])} | {number(value['baseline_mean'])} | {number(value['agent_minus_baseline'])} | {value['paired_cases']} |")
        return rows
    lines=['# Full agent versus single-pass baseline','',f"**{summary['scope']}** — {summary['recorded_pairs']} / {summary['planned_pairs']} pairs recorded.",'',
        'Same questions, same underlying model, same collected evidence, same answer-only judge criteria.',
        'Quality values are mean per-question rates from jointly assessed cases. Lower unsupported-claim rates are better.',
        '**Resource caveat:** '+summary['resource_caveat'], '', '## Aggregate results','']+table(summary['metrics'])
    lines+=['','## Results by category','']
    for category,group in summary['categories'].items():
        lines += [f"### {category} ({group['recorded']} / {group['planned']})",'']+table(group['metrics'])+['']
    lines+=['## Examples and counterexamples','', 'These are descriptive case-level differences, not statistical proof or investment performance.']
    for outcome,items in summary['examples'].items():
        lines+=['',f'### {outcome.replace("_"," ")}', '']
        if not items:lines+=['No qualifying measured examples yet.'];continue
        for item in items:
            changes=', '.join(f'{k}: {v:+.3f}' for k,v in item['quality_deltas'].items()) or 'Quality not assessed'
            lines += [f"- **{item['case_id']}**: {item['question']} ([details]({item['artifact']})). {changes}. Agent calls: {item['agent']['model_calls']}; baseline calls: {item['baseline']['model_calls']}."]
    lines += ['', '## Interpretation limits','',
        '- Prepared evidence includes deterministic calculation results. This tests using evidence and calculations, not isolated mental arithmetic or retrieval superiority.',
        '- Agent runs were recorded earlier; baseline calls occur later. Runtime comparisons are descriptive and can be affected by hardware load and caching.',
        '- The judge does not see system labels or self-review, but answer style may identify a system. LLM judgments require human calibration.',
        '- Citation/unsupported-claim comparisons exclude partial claim assessments on either side. Missing assessments and failures remain visible in JSON.',
        '- No composite score or preselected winning example is used. Equal measured quality with extra calls is reported as no measured quality gain.',
        '- Repeated cases, small synthetic source corpora and technology-sector concentration limit generalization. No claim of superiority is warranted from this report alone.']
    return '\n'.join(lines)+'\n'
