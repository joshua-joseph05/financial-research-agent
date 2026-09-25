"""Deterministic benchmark diagnostics. These do not establish semantic truth."""
from datetime import date
from decimal import Decimal, InvalidOperation


def rate(passed,total):return {'passed':passed,'total':total,'rate':passed/total if total else None}


def evidence_inventory(run):
    records={e['id']:e for e in run['trace'].get('provided_evidence',[])}
    sources={s['id']:s for s in run['trace'].get('provided_sources',[])}
    def add(payload):
        if not isinstance(payload,dict):return
        evidence=payload.get('evidence',[])
        if isinstance(evidence,dict):records[evidence['id']]=evidence
        else:
            for e in evidence:records[e['id']]=e
        for s in payload.get('sources',[]):sources[s['id']]=s
    # Snapshot evidence is a dict, tool result evidence is a list.
    for call in run['trace']['tool_calls']:
        value=call.get('result',{})
        if isinstance(value.get('evidence'),dict):
            records[value['evidence']['id']]=value['evidence']
            if value.get('source'):sources[value['source']['id']]=value['source']
        else:add(value)
    state=run['trace'].get('research_state') or {}
    records.update(state.get('observations',{}));sources.update(state.get('sources',{}))
    report=run.get('report') or {}
    if run['target']!='sentiment':add(report)
    for article in run['trace'].get('articles',{}).values():
        records[article['id']]={'id':article['id'],'source_id':article['id'],'text':article['body']}
        sources[article['id']]={'id':article['id'],'uri':article['url'],'title':article['title']}
    for sample in run['trace'].get('sentiment_results',[]):
        for arg in sample.get('arguments',[]):
            records[arg['id']]={'id':arg['id'],'source_id':arg['article_id'],'text':arg['point']+' Supporting quote: '+arg['quote'],'input_ids':[arg['article_id']]}
    return records,sources


def answer_claims(run):
    """Stable segments include narrative and UI explanation fields, not just approved findings."""
    report=run.get('report') or {};claims=[]
    def add(text,ids=(),kind='answer'):
        if text and isinstance(text,str):claims.append({'id':f'claim-{len(claims)+1:03}','text':text,'evidence_ids':list(ids),'kind':kind})
    if run.get('clarification'):add(run['clarification'],kind='clarification')
    if run['target']!='sentiment':
        findings=report.get('findings',[])
        for f in findings:add(f['text'],f.get('evidence_ids',[]))
        if report.get('answer') and not findings:add(report['answer'])
        # Findings cover the rendered live answer, but synthetic free prose may add claims.
        if findings and report.get('synthetic'):add(report.get('answer'),[i for f in findings for i in f.get('evidence_ids',[])])
        for section in report.get('answer_sections',[]):add(section.get('text'),section.get('evidence_ids',[]))
        guide=report.get('beginner_guide') or {}
        add(guide.get('overview'),kind='explanation')
        for section in guide.get('explanations',[]):
            add(section.get('explanation'),section.get('evidence_ids',[]),'explanation')
            add(section.get('why_it_matters'),section.get('evidence_ids',[]),'explanation')
        for item in report.get('ideas',[]):
            refs=[i for claim in item.get('reasons',[])+item.get('risks',[]) for i in claim.get('evidence_ids',[])]
            add(f"{item['ticker']}: {item['action']}",refs,'decision')
            for claim in item.get('reasons',[])+item.get('risks',[]):add(claim.get('text'),claim.get('evidence_ids',[]))
            add(item.get('timing'),refs,'guidance');add(item.get('caution'),refs,'limitation')
        for text in report.get('limitations',[]):add(text,kind='limitation')
    for sample in run['trace'].get('sentiment_results',[]):
        add(f"{sample.get('ticker')}: {sample.get('status')}; retrieved sample sentiment: {sample.get('overall_sentiment')}",[a['id'] for a in sample.get('arguments',[])],'sentiment_status')
        for limitation in sample.get('limitations',[]):add(limitation,kind='limitation')
        for arg in sample.get('arguments',[]):add(arg['point'],[arg['article_id']],'sentiment_argument')
        synthesis=sample.get('synthesis') or {}
        for value in synthesis.values():
            for claim in value if isinstance(value,list) else [value]:
                add(claim.get('text'),claim.get('argument_ids',[]),'sentiment_summary')
    return claims


def calculation_check(record,records,seen=None):
    """Independent Decimal oracle; does not call the production calculator."""
    try:
        seen=set() if seen is None else seen
        if record['id'] in seen:raise ValueError('Cyclic calculation lineage')
        inputs=[records[i] for i in record.get('input_ids',[])]
        for source in inputs:
            if source.get('operation') and calculation_check(source,records,seen|{record['id']})['status']!='pass':
                raise ValueError('Invalid upstream calculation')
        if len(inputs)!=2:raise ValueError('Exactly two inputs required')
        a,b=inputs;x,y=Decimal(a['value']),Decimal(b['value'])
        if not x.is_finite() or not y.is_finite():raise ValueError('Nonfinite input')
        if a['ticker']!=b['ticker'] or a.get('unit')!=b.get('unit'):raise ValueError('Company or unit mismatch')
        if record.get('ticker')!=a['ticker'] or record.get('period')!=a.get('period'):raise ValueError('Output scope/period mismatch')
        if a.get('period_type') or b.get('period_type'):
            for item in inputs:
                if item.get('period_type')!='annual':raise ValueError('Nonannual input')
                duration=(date.fromisoformat(item['period_end'])-date.fromisoformat(item['period_start'])).days+1
                if not 350<=duration<=380:raise ValueError('Invalid annual duration')
        op=record['operation']
        if op=='operating_margin':
            if a.get('metric')!='operating_income' or b.get('metric')!='revenue' or a.get('period')!=b.get('period') or y<=0:raise ValueError('Invalid margin inputs')
            if (a.get('period_start'),a.get('period_end'))!=(b.get('period_start'),b.get('period_end')):raise ValueError('Fiscal mismatch')
            expected=x/y*100;unit='percent'
        elif op in ('growth','margin_change'):
            if not a.get('period') or not b.get('period') or a['period']<=b['period']:raise ValueError('Reversed or missing periods')
            if a.get('period_type') and not 350<=(date.fromisoformat(a['period_end'])-date.fromisoformat(b['period_end'])).days<=380:raise ValueError('Nonadjacent years')
            if op=='growth':
                if a.get('metric')!=b.get('metric') or y<=0:raise ValueError('Invalid growth base/metric')
                expected=(x-y)/y*100;unit='percent'
            else:
                if a.get('metric')!='operating_margin' or b.get('metric')!='operating_margin' or a.get('unit')!='percent':raise ValueError('Invalid margin change inputs')
                expected=x-y;unit='percentage_points'
        else:return {'id':record['id'],'status':'unassessed','reason':'Unsupported calculation operation'}
        expected=expected.quantize(Decimal('0.0001'))
        actual=Decimal(record['value'])
        passed=actual.is_finite() and actual==expected and record['unit']==unit
        return {'id':record['id'],'status':'pass' if passed else 'fail','expected_value':str(expected),'expected_unit':unit,'actual_value':record.get('value')}
    except (KeyError,TypeError,ValueError,InvalidOperation,ArithmeticError) as error:
        return {'id':record['id'],'status':'fail','reason':str(error)}


def provenance_valid(key,records,sources,visiting=None):
    visiting=set() if visiting is None else visiting
    if key in visiting or key not in records:return False
    record=records[key]
    if record.get('source_id') not in sources:return False
    return all(provenance_valid(i,records,sources,visiting|{key}) for i in record.get('input_ids',[]))


def deterministic_metrics(case,run):
    records,sources=evidence_inventory(run);claims=answer_claims(run)
    calculations=[calculation_check(e,records) for e in records.values() if e.get('operation')]
    judged_calc=[c for c in calculations if c['status']!='unassessed']
    cited=[c for c in claims if c['evidence_ids']]
    decisions=[d['output'].get('tool') or {'name':'<missing_tool>','arguments':{}} for d in run['trace']['model_decisions'] if d.get('output',{}).get('action')=='tool']
    allowed=set(case.allowed_tools)
    def valid_tool(call):
        args=call.get('arguments',{});targets=([args['ticker']] if 'ticker' in args else [])+args.get('tickers',[])
        from app.evaluation.sources import NAMES
        from app.tools.registry import SPECS
        from app.ideas.tools import WebSearchArgs
        from app.ideas.sentiment import ConsultArgs
        try:
            schema={'search_web':WebSearchArgs,'consult_sentiment':ConsultArgs}.get(call['name'])
            (schema or SPECS[call['name']][0]).model_validate(args)
        except (KeyError,ValueError):return False
        aliases={v.upper():k for k,v in NAMES.items()}
        return call['name'] in allowed and (not case.tickers or all(aliases.get(t.upper(),t.upper()) in case.tickers for t in targets))
    observed={c['name'] for c in run['trace']['tool_calls']}
    if run['trace'].get('sentiment_results'):observed.add('consult_sentiment')
    if calculations:observed.add('calculate_financial_metrics')
    missing=[g for g in case.required_tool_groups if not set(g)&observed]
    argument_checks=[];source_checks=[];today=date.fromisoformat(run['as_of'])
    for sample in run['trace'].get('sentiment_results',[]):
        for source in sample.get('sources',[]):
            try:age=(today-date.fromisoformat(source['published'][:10])).days;recent=0<=age<=30
            except (ValueError,KeyError,TypeError):age=None;recent=False
            source_checks.append({'id':source['id'],'age_days':age,'recent':recent})
        for arg in sample.get('arguments',[]):
            article=run['trace'].get('articles',{}).get(arg['article_id']);body=article['body'] if article else ''
            argument_checks.append({'id':arg['id'],'citation_exists':bool(article),
                'quote_exists':bool(arg.get('quote')) and arg['quote'] in body,
                'attribution_present':arg.get('attribution','') in body if arg.get('attribution') else None})
    attrs=[a for a in argument_checks if a['attribution_present'] is not None]
    research=run['trace'].get('research_state') or {}
    bad_tools=[c for c in run['trace']['tool_calls'] if c.get('status') in ('error','no_data')]
    return {
        'routing_accuracy':rate(int(run['workflow'] in case.expected_workflows),1) if run['target']=='assistant' else rate(0,0),
        'reported_completion':bool((run.get('report') or {}).get('complete')),
        'tool_selection_label_precision':rate(sum(valid_tool(c) for c in decisions),len(decisions)),
        'required_tool_group_coverage':rate(len(case.required_tool_groups)-len(missing),len(case.required_tool_groups)),
        'missing_tool_groups':missing,
        'calculation_accuracy':rate(sum(c['status']=='pass' for c in judged_calc),len(judged_calc)),
        'calculation_details':calculations,
        'citation_integrity':rate(sum(all(provenance_valid(i,records,sources) for i in c['evidence_ids']) for c in cited),len(cited)),
        'claim_segments':len(claims),'uncited_segments':len(claims)-len(cited),
        'sentiment_recency':rate(sum(c['recent'] for c in source_checks),len(source_checks)),
        'sentiment_quote_integrity':rate(sum(a['quote_exists'] and a['citation_exists'] for a in argument_checks),len(argument_checks)),
        'sentiment_attribution_presence':rate(sum(a['attribution_present'] for a in attrs),len(attrs)),
        'sentiment_sources':source_checks,'sentiment_arguments':argument_checks,
        'tool_failures':len(bad_tools),'model_failures':sum(c['status']=='error' for c in run['telemetry'].get('calls',[])),
        'stop_reason':research.get('stop_reason'),
        'gap_decisions':sum(d.get('output',{}).get('sufficient') is False or d.get('output',{}).get('coverage')=='needs_more_evidence' for d in run['trace']['model_decisions']),
    }
