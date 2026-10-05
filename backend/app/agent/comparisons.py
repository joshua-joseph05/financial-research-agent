"""Comparable growth conclusions derived from reproduced calculations."""
from collections import defaultdict
from decimal import Decimal
from itertools import combinations
from app.schemas import Evidence, Finding
from app.tools.calculations import calculate


def growth_comparison_findings(observations):
    groups=defaultdict(lambda:defaultdict(list))
    for record in observations.values():
        if record.get('operation')!='growth' or len(record.get('input_ids',[]))!=2:
            continue
        try:
            inputs=[Evidence.model_validate(observations[k]) for k in record['input_ids']]
            newer,older=inputs
            value,unit=calculate('growth',inputs)
            if value!=record['value'] or unit!=record['unit']:continue
            if any(e.scope!='company' or e.segment or e.period_type!='annual' or e.operation or e.ticker!=record['ticker'] for e in inputs):continue
            if not all(e.period_start and e.period_end and e.metric and e.unit for e in inputs):continue
            key=(newer.metric,newer.unit,newer.period_start,newer.period_end,older.period_start,older.period_end)
            groups[key][record['ticker']].append(record)
        except (KeyError,ValueError,ArithmeticError):
            continue
    findings=[]
    for key,issuers in sorted(groups.items()):
        # Ambiguous duplicate calculations are not silently selected.
        records=[items[0] for ticker,items in sorted(issuers.items()) if len(items)==1]
        for left,right in combinations(records,2):
            a,b=Decimal(left['value']),Decimal(right['value'])
            metric=key[0].replace('_',' ')
            text=f"From {key[5]} to {key[3]}, {left['ticker']} {metric} changed by {a}% and {right['ticker']} by {b}%. "
            if a==b:
                text+='Their percentage changes are equal at the displayed precision.'
            else:
                high,low=(left,right) if a>b else (right,left)
                if min(a,b)>0:
                    text+=f"Both increased; {high['ticker']} {metric} grew faster in percentage terms than {low['ticker']}."
                elif max(a,b)<0:
                    text+=f"Both decreased; {high['ticker']} {metric} declined less in percentage terms than {low['ticker']}."
                else:
                    def direction(v):return 'increased' if v>0 else 'decreased' if v<0 else 'was unchanged at the displayed precision'
                    text+=f"{left['ticker']} {direction(a)}, while {right['ticker']} {direction(b)}."
            findings.append(Finding(id=f"derived:comparison:{left['id']}:{right['id']}",text=text,evidence_ids=[left['id'],right['id']],scope='company').model_dump())
    return findings
