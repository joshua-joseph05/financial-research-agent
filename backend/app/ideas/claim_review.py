"""Claim-scoped verification: keep uncited evidence out of each review item."""
from collections import Counter
from pydantic import Field
from app.schemas import Model


class SupportQuote(Model):
    evidence_id: str
    quote: str = Field(min_length=1, max_length=500)


class ClaimCheck(Model):
    claim_id: str
    supported: bool
    quotes: list[SupportQuote] = Field(default_factory=list, max_length=4)


class ActionCheck(Model):
    ticker: str
    supported: bool


class ClaimReview(Model):
    actions: list[ActionCheck] = Field(default_factory=list, max_length=3)
    checks: list[ClaimCheck] = Field(max_length=12)


class InformationalClaimReview(ClaimReview):
    answers_question: bool = Field(description='Whether the displayed supported findings, sentiment report and checklist answer the original question for the supplied companies. Source support alone is not answer coverage.')
    remaining_question: str = Field(max_length=350, description='Missing requested information, or empty when the question is answered.')


def review_items(ideas, observations):
    items=[]
    for idea in ideas:
        for kind in ('reasons','risks'):
            for index, claim in enumerate(idea[kind]):
                evidence={};pending=list(claim['evidence_ids'])
                while pending:
                    key=pending.pop()
                    if key in evidence or key not in observations:continue
                    record=observations[key]
                    if record.get('ticker')!=idea['ticker']:continue
                    evidence[key]=record
                    pending.extend(record.get('input_ids',[]))
                items.append({'claim_id':f"{idea['ticker']}:{kind}:{index}", 'text':claim['text'], 'evidence':evidence})
    return items


def python_verified_claim_ids(ideas, observations, sources):
    """Approve only exact canonical numerical statements reproduced from their citations."""
    from app.ideas.models import Rationale
    from app.ideas.numeric_rationales import grounded_numeric_rationale
    approved=set()
    for idea in ideas:
        for kind in ('reasons','risks'):
            for index, raw in enumerate(idea[kind]):
                try:
                    claim=Rationale.model_validate(raw)
                    pending=list(claim.evidence_ids);seen=set()
                    while pending:
                        key=pending.pop()
                        if key in seen:continue
                        seen.add(key)
                        record=observations[key]
                        if record.get('ticker')!=idea['ticker'] or record.get('value') is None:
                            raise ValueError('Not issuer-matched numerical evidence')
                        pending.extend(record.get('input_ids',[]))
                    if not seen:continue
                    rebuilt=grounded_numeric_rationale(claim,observations,sources)
                    if rebuilt==claim:
                        approved.add(f"{idea['ticker']}:{kind}:{index}")
                except (ValueError, KeyError, TypeError, RecursionError):
                    continue
    return approved


def reviewed_tickers(ideas, items, review, *, python_verified_ids=frozenset(), require_action=True):
    counts=Counter(c.claim_id for c in review.checks)
    by_id={c.claim_id:c for c in review.checks}
    valid={}
    for item in items:
        check=by_id.get(item['claim_id'])
        supported=bool(check and check.supported and counts[item['claim_id']]==1 and check.quotes)
        if supported:
            supported=all(q.evidence_id in item['evidence'] and q.quote.strip() and q.quote in item['evidence'][q.evidence_id]['text'] for q in check.quotes)
        valid[item['claim_id']]=supported or item['claim_id'] in python_verified_ids
    action_counts=Counter(c.ticker for c in review.actions)
    approved_actions={c.ticker for c in review.actions if c.supported and action_counts[c.ticker]==1}
    return {'approved_claim_ids':[key for key, supported in valid.items() if supported], 'checks':[{'ticker':idea['ticker'], 'supported':(not require_action or idea['ticker'] in approved_actions) and bool(idea['reasons'] and idea['risks']) and all(valid.get(f"{idea['ticker']}:{kind}:{index}",False) for kind in ('reasons','risks') for index in range(len(idea[kind]))), 'explanation':'Numerical facts require Python evidence validation; interpretations require source review and exact excerpts. Actions require separate review.'} for idea in ideas]}


def citation_topic_issue(text, records):
    """Reject clear topic/citation mismatches; semantic source review still follows."""
    import re
    from app.agent.claim_guards import passage_claim_issue, financial_trend_citation_issue
    issue=passage_claim_issue(text,records) or financial_trend_citation_issue(text,records)
    if issue:return issue
    claim=text.lower().replace('_',' ')
    cited=' '.join(r.get('text','') for r in records).lower().replace('_',' ')
    metrics={r.get('metric') for r in records}
    # Structured observations from these tools are realized annual values or
    # dated prices. Earnings guidance is textual evidence and still needs review.
    leaves=[r for r in records if not r.get('operation')]
    historical_only=bool(leaves) and all(r.get('value') is not None and
        (r.get('period_type') in ('annual','quarterly') or r.get('metric')=='market_close') for r in leaves)
    future_terms=list(re.finditer(r'\b(?:projected|projections?|forecast(?:s|ed|ing)?)\b',claim))
    asserted_future=any(not re.search(r'\bnot\s+(?:a\s+|an\s+|future\s+)?$',claim[:m.start()]) for m in future_terms)
    if historical_only and asserted_future:
        return 'Historical figures are not forecasts or projections; describe the reported periods, or cite actual guidance'
    topics={'revenue':('revenue',), 'operating_income':('operating income','operating profit'),
            'operating_margin':('operating margin',), 'operating_cash_flow':('operating cash flow','cash flow from operations'),
            'capital_expenditure':('capital expenditure','capital spending','capex')}
    for metric, phrases in topics.items():
        if any(p in claim for p in phrases) and metric not in metrics and not any(p in cited for p in phrases):
            return f'The cited evidence does not discuss {metric}; cite matching evidence or remove that claim'
    if re.search(r'\b(?:analysts?|commentary|one analysis|an analysis)\b',claim) and not re.search(r'\b(?:analysts?|commentary|analysis)\b',cited):
        return 'Attributed commentary needs a source containing that commentary; a filing risk is not analyst evidence'
    return None
