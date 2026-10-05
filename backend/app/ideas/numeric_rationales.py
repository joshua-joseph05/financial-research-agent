"""Render numeric-only claims from evidence; numbers cannot establish business causes."""
from app.agent.attribution import calculation_findings
from app.agent.graph import structural_check


def grounded_numeric_rationale(claim, observations, sources):
    records={}
    pending=list(claim.evidence_ids)
    while pending:
        key=pending.pop()
        if key in records:
            continue
        record=observations.get(key)
        if record is None:
            return claim  # The ordinary citation check supplies repair feedback.
        records[key]=record
        pending.extend(record.get('input_ids',[]))
    if not records or any(r.get('value') is None for r in records.values()):
        return claim  # Passage-based interpretations still require source review.
    canonical={f['evidence_ids'][0]:f for f in calculation_findings(observations)}
    texts=[]
    for key in dict.fromkeys(claim.evidence_ids):
        record=records[key]
        if record.get('operation'):
            finding=canonical.get(key)
            if finding is None:
                raise ValueError('No canonical statement for the cited calculation')
        else:
            period=f" for {record['period']}" if record.get('period') else ''
            label=(record.get('metric') or 'reported value').replace('_',' ')
            text=f"{record['ticker']} {label}{period}: {record['value']} {record.get('unit') or ''}."
            finding={'id':'numeric:'+key,'text':text,'evidence_ids':[key],
                     'scope':record.get('scope'),'segment':record.get('segment'),
                     'fiscal_years':record.get('fiscal_years',[]),'explains_change':False}
        finding=dict(finding)
        if record.get('period_type')!='annual':
            finding['text']=finding['text'].replace('annual period ending','period ending')
        if record.get('scope')=='segment':
            finding['text']=f"Segment {record.get('segment') or '(unspecified)'}: "+finding['text']
        elif record.get('scope')!='company' and record.get('metric')!='market_close':
            finding['text']='Scope unspecified: '+finding['text']
        issue=structural_check(finding,{'observations':observations,'sources':sources,'plan':{}})
        if issue:
            raise ValueError('Numeric rationale failed evidence validation: '+issue)
        texts.append(finding['text'])
    return type(claim)(text=' '.join(texts),evidence_ids=claim.evidence_ids)
