"""Coverage-explicit reports; no single overall winner."""
from statistics import mean,median
from . import VERSION
from app.evaluation.baseline_report import measures

QUALITY=('task_completion','citation_validity','citation_correctness','citation_completeness',
         'supported_claim_rate','unsupported_claim_rate','contradicted_claim_rate','calculation_accuracy')

def aggregate(pairs):
    output={}
    for metric in QUALITY:
        rows=[]
        for pair in pairs:
            a,b=[pair['corrected'][s]['metrics'][metric] for s in ('agent','baseline')]
            complete=metric in ('task_completion','citation_validity','calculation_accuracy') or all(pair['corrected'][s]['metrics']['claim_assessment_coverage']['rate']==1 for s in ('agent','baseline'))
            if metric in ('citation_correctness','citation_completeness'):complete=complete and all(not pair['corrected'][s]['metrics'].get('citation_judge_errors') for s in ('agent','baseline'))
            if complete and a['rate'] is not None and b['rate'] is not None:rows.append((a,b))
        output[metric]={'paired_questions':len(rows),'missing_pairs':len(pairs)-len(rows),
            'agent_mean':mean(a['rate'] for a,b in rows) if rows else None,
            'baseline_mean':mean(b['rate'] for a,b in rows) if rows else None,
            'agent_minus_baseline':mean(a['rate']-b['rate'] for a,b in rows) if rows else None,
            'agent_contributing_units':sum(a['total'] for a,b in rows),
            'baseline_contributing_units':sum(b['total'] for a,b in rows)}
    resources={}
    for system in ('agent','baseline'):
        values=[measures(p['original'],system) for p in pairs]
        resources[system]={k:mean(v[k] for v in values) if values else None for k in ('latency_seconds','model_calls','tool_calls')}
        resources[system]['median_latency_seconds']=median(v['latency_seconds'] for v in values) if values else None
        resources[system]['questions']=len(values)
    return {'quality':output,'resources':resources}

def reliability(pairs):
    output={}
    for system in ('agent','baseline'):
        results=[p['corrected'][system] for p in pairs]
        jobs=[job for r in results for job in [r['task']]+r['claim_jobs']+r.get('citation_jobs',[])]
        counts={'judge_jobs':len(jobs),'successful_jobs':sum(j['status']=='ok' for j in jobs),
            'failed_jobs':sum(j['status']=='judge_error' for j in jobs),'retried_jobs':sum(j['retry_count']>0 for j in jobs),
            'attempts':sum(len(j['attempts']) for j in jobs),'failed_attempts':sum(a['status']=='error' for j in jobs for a in j['attempts']),
            'total_claims':sum(r['metrics']['total_claims'] for r in results),
            'evaluated_claims':sum(r['metrics']['evaluated_claims'] for r in results),
            'unjudgeable_claims':sum(r['metrics']['unjudgeable_claims'] for r in results),
            'procedural_claims':sum(r['metrics']['procedural_claims'] for r in results),
            'answer_system_errors':sum(r['system_status']=='error' for r in results)}
        for name,count in [('judge_success_rate','successful_jobs'),('judge_error_rate','failed_jobs'),('retry_frequency','retried_jobs')]:
            counts[name]=counts[count]/len(jobs) if jobs else None
        output[system]=counts
    return output

def summary(pairs,old,planned):
    return {'version':VERSION,'recorded_pairs':len(pairs),'planned_pairs':planned,
            'status':'complete' if len(pairs)==planned else 'partial','aggregate':aggregate(pairs),
            'categories':{c:{'questions':sum(p['original']['category']==c for p in pairs),
                **aggregate([p for p in pairs if p['original']['category']==c])} for c in old['categories']},
            'reliability':reliability(pairs),'original_metrics':old['metrics'],
            'pairs':[{'id':p['original']['id'],'question':p['original']['question'],'category':p['original']['category'],
                'metrics':{s:p['corrected'][s]['metrics'] for s in ('agent','baseline')},
                'resources':{s:measures(p['original'],s) for s in ('agent','baseline')},
                'task_judgments':{s:p['corrected'][s]['task']['judgment'] for s in ('agent','baseline')},
                'artifact':p['original']['id']+'-v2.json'} for p in pairs]}

def render(report):
    def n(x):return 'Unassessed' if x is None else f'{x:.3f}'
    def table(quality):
        lines=['| Quality metric | Agent | Baseline | Paired questions | Agent / baseline units |',
               '| --- | ---: | ---: | ---: | ---: |']
        for k,v in quality.items():lines.append(f"| {k} | {n(v['agent_mean'])} | {n(v['baseline_mean'])} | {v['paired_questions']} | {v['agent_contributing_units']} / {v['baseline_contributing_units']} |")
        return lines
    lines=['# Corrected evaluator v2 comparison','',f"{report['recorded_pairs']}/{report['planned_pairs']} pairs recorded — {report['status']}.",'',
        'Answers, answering latency and answering calls are unchanged. Only evaluation was rerun.',
        'Quality values are mean per-question rates over jointly assessed pairs. Units are criteria-completion questions, references, factual segments or calculation records as appropriate. Missing judgments are not failures of either answering system. Semantic claim comparisons require complete claim-judgment coverage on both answers; unjudgeable claims are counted separately and excluded from factual-rate denominators.',
        'Baseline latency excludes collecting its inherited evidence and Python calculations. This is not an end-to-end speed comparison.','', '## Aggregate','']+table(report['aggregate']['quality'])
    lines+=['','| Resource | Agent | Baseline | Questions per system |','| --- | ---: | ---: | ---: |']
    a,b=[report['aggregate']['resources'][s] for s in ('agent','baseline')]
    for k in ('latency_seconds','median_latency_seconds','model_calls','tool_calls'):lines.append(f"| {k} | {n(a[k])} | {n(b[k])} | {a['questions']} |")
    lines+=['','## Original versus corrected','', 'The unsupported-claim definition changed; old and new rates do not measure the same construct. Coverage also changes.','',
            '| Metric | Old agent | Old baseline | Old pairs | V2 agent | V2 baseline | V2 pairs |','| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for k in ('task_completion','citation_correctness','calculation_accuracy','unsupported_claim_rate'):
        old=report['original_metrics'][k];new=report['aggregate']['quality'][k]
        lines.append(f"| {k} | {n(old['agent_mean'])} | {n(old['baseline_mean'])} | {old['paired_cases']} | {n(new['agent_mean'])} | {n(new['baseline_mean'])} | {new['paired_questions']} |")
    lines+=['','## Categories','', 'Two questions per category: descriptive examples, not strong statistical conclusions.']
    for category,data in report['categories'].items():lines+=['',f"### {category} ({data['questions']} questions)",'']+table(data['quality'])
    lines+=['','## Evaluator reliability','', '| Measure | Agent answers | Baseline answers |','| --- | ---: | ---: |']
    a,b=[report['reliability'][s] for s in ('agent','baseline')]
    for k in a:lines.append(f'| {k} | {n(a[k])} | {n(b[k])} |')
    lines+=['','Rates above use judge_jobs as denominator; attempts and claim counts are reported separately. Unjudgeable claims are valid judgments with insufficient evidence, not judge errors.','', '## Matched questions','']
    for pair in report['pairs']:
        lines+=[f"### {pair['id']}",pair['question'],'',f"[Full original outputs and corrected judgments]({pair['artifact']})",'']
        for system in ('agent','baseline'):
            m=pair['metrics'][system];r=pair['resources'][system]
            scores='; '.join(f"{k}={n(m[k]['rate'])} ({m[k]['passed']}/{m[k]['total']})" for k in QUALITY)
            lines += [f"- **{system}**: {scores}. Time {r['latency_seconds']:.1f}s; model calls {r['model_calls']}; tool calls {r['tool_calls']}; judge errors {m['judge_error_rate']['passed']}/{m['judge_error_rate']['total']}."]
            task=pair['task_judgments'][system]
            if task:
                for c in task['criteria']:lines.append(f"  - {c['criterion_id']}: {c['verdict']} — {c['reason']}")
    lines+=['','## Limitations','',
        '- Scores apply to frozen fictional evidence and the saved gemma4:e4b answers. No live-market or investment-performance claims.',
        '- LLM judgment remains fallible. Exact quotation validation proves presence, not semantic entailment. A separate manual audit is required.',
        '- Supported facts without citations are now support successes and citation-completeness failures. Unsupported and contradicted are separate rates, neither automatically a hallucination rate.',
        '- Segment-level assessment can combine multiple assertions and duplicate summary text; contributing-unit counts expose this limitation.',
        '- Calculation record accuracy includes lineage. A correct displayed number can coexist with a failed structured calculation.',
        '- No aggregate winner is assigned when dimensions disagree. Production and baseline behavior were not optimized.']
    return '\n'.join(lines)+'\n'
