"""Per-company retrieval coverage, separate from claim support and answer quality."""
from typing import Literal
from datetime import date
from decimal import Decimal, InvalidOperation
from pydantic import Field, model_validator
from app.schemas import Model


class CoverageTarget(Model):
    ticker: str = Field(min_length=1, max_length=12)
    needs: list[Literal['business', 'risks', 'financial_values', 'calculated_metrics']] = Field(min_length=1, max_length=4)
    financial_metrics: list[Literal['revenue','operating_income','net_income','operating_cash_flow','capital_expenditure']] = Field(default_factory=lambda:['revenue','operating_income'], max_length=5, description='Only raw metrics needed by the original question. Cash-flow questions use operating_cash_flow; profit growth uses operating_income; margin needs revenue and operating_income. Empty when financial_values is not needed.')
    minimum_periods: int = Field(default=1, ge=1, le=10, description='Required number of distinct comparable annual periods per requested metric. Use two for change or growth across two years, one for a single year. Exact requested years still require final question-coverage review.')

    @model_validator(mode='after')
    def require_named_financial_metrics(self):
        if 'financial_values' in self.needs and not self.financial_metrics:
            raise ValueError('financial_values requires at least one requested financial metric; otherwise use only the non-financial needs actually requested')
        return self



def financial_coverage(target, records):
    # Older saved plans retain their existing contract. New model schemas require
    # explicit metrics and period counts, without inferring dates from the ticker.
    if 'financial_metrics' not in target:
        return all(any(r.get('metric')==metric and r.get('value') is not None and not r.get('operation') for r in records) for metric in ('revenue','operating_income'))
    metrics=set(target['financial_metrics'])
    if not metrics:return False
    periods={metric:set() for metric in metrics}
    for record in records:
        metric=record.get('metric')
        if metric not in periods or record.get('operation') or record.get('period_type')!='annual':continue
        if record.get('scope')!='company' or not record.get('unit'):continue
        try:
            if not Decimal(str(record.get('value'))).is_finite():continue
            end=date.fromisoformat(record.get('period_end') or record.get('period') or '')
        except (InvalidOperation, ValueError, TypeError):continue
        periods[metric].add((end,record['unit']))
    common=set.intersection(*periods.values())
    # Multiple currencies or restated duplicates at one year-end are one period.
    return any(len({end for end,unit in common if unit==currency})>=target.get('minimum_periods',1) for currency in {unit for _,unit in common})


def coverage_status(plan, observations):
    rows=[]
    for target in plan.get('coverage_targets', []):
        ticker=target['ticker'].upper()
        records=[r for r in observations.values() if r.get('ticker','').upper()==ticker]
        present={
            'business':any(r.get('section')=='business' for r in records),
            'risks':any(r.get('section')=='risks' for r in records),
            'financial_values':financial_coverage(target,records),
            'calculated_metrics':any(r.get('operation') for r in records),
        }
        rows.append({'ticker':ticker, 'retrieved':[n for n in target['needs'] if present[n]],
                     'missing':[n for n in target['needs'] if not present[n]]})
    return rows


def coverage_gaps(plan, observations):
    return [f"{r['ticker']}: still need {', '.join(r['missing'])}" for r in coverage_status(plan, observations) if r['missing']]


def numeric_review_ready(plan, observations, new_ids):
    """Declared numerical tasks can proceed to independent final coverage review."""
    from app.agent.attribution import reported_financial_findings, calculation_findings
    allowed={'financial_values','calculated_metrics'}
    required=set(plan.get('evidence_requirements', []))
    if not required or not required <= allowed or plan.get('answer_type') == 'historical_explanation':
        return False
    if 'calculated_metrics' in required and not calculation_findings(observations):
        return False
    targets=plan.get('coverage_targets', [])
    if not targets or any(not t['needs'] or not set(t['needs']) <= allowed for t in targets):
        return False
    if coverage_gaps(plan, observations):
        return False
    rendered={key for finding in reported_financial_findings(observations)+calculation_findings(observations) for key in finding['evidence_ids']}
    return bool(new_ids) and set(new_ids) <= rendered


def meaningful_requirements(items):
    """Remove exact empty sentinels, never sentences describing missing evidence."""
    empty={'', 'none', 'n/a', 'null', 'not applicable', '[]', 'no open questions', 'no unresolved requirements'}
    return [item for item in items if item.strip().casefold().rstrip('.') not in empty]


def calculation_gap_options(plan, observations, specs):
    """Surface valid, not-yet-executed tool options for uncovered companies.

    Suggestions only: the agent retains every tool and final evidence review.
    Operand validity and previously executed calls are handled by the registry.
    """
    missing={r['ticker'] for r in coverage_status(plan,observations) if 'calculated_metrics' in r['missing']}
    choices=next((s['input_schema'].get('anyOf',[]) for s in specs if s['name']=='calculate_financial_metrics'),[])
    options=[]
    for choice in choices:
        props=choice.get('properties',{})
        ids=[item.get('const') for item in props.get('evidence_ids',{}).get('prefixItems',[])]
        operation=props.get('operation',{}).get('const')
        if not ids or not operation or any(key not in observations for key in ids):continue
        tickers={observations[key].get('ticker','').upper() for key in ids}
        if len(tickers)!=1 or not tickers<=missing:continue
        options.append({'ticker':next(iter(tickers)),'tool':{'name':'calculate_financial_metrics','arguments':{'operation':operation,'evidence_ids':ids}}})
        if len(options)>=8:break
    return options
