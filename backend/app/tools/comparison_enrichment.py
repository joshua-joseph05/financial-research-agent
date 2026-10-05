"""Deterministic growth enrichment of already-fetched comparison data."""
from app.schemas import ToolCall


def add_revenue_growth(registry, result):
    result = result.model_copy(deep=True)
    local = {e.id:e.model_dump() for e in result.evidence}
    for ticker in sorted({e.ticker for e in result.evidence if e.ticker}):
        rows = [e for e in result.evidence if e.ticker==ticker and e.metric=='revenue'
                and e.value is not None and not e.operation and e.period_end]
        dates=sorted({e.period_end for e in rows},reverse=True)[:2]
        if len(dates)!=2:continue
        pairs=[[e for e in rows if e.period_end==day] for day in dates]
        # Ambiguity stays a gap. Do not guess between duplicate scopes/units.
        if any(len(pair)!=1 for pair in pairs):
            result.limitations.append(f'{ticker}: ambiguous revenue periods; growth was not inferred.')
            continue
        new, old = (pair[0] for pair in pairs)
        if (new.scope, new.segment, new.concept) != (old.scope, old.segment, old.concept):
            result.limitations.append(f'{ticker}: incompatible revenue scopes; growth was not inferred.')
            continue
        if any(e.period_type!='annual' or e.scope!='company' or e.segment for e in (new,old)):
            result.limitations.append(f'{ticker}: growth requires explicit consolidated annual periods.')
            continue
        ids=[new.id, old.id]
        if any(e.operation=='growth' and e.input_ids==ids for e in result.evidence):continue
        computed=registry.execute(ToolCall(name='calculate_financial_metrics',arguments={'operation':'growth','evidence_ids':ids}),local)
        result.evidence.extend(computed.evidence)
        result.sources.extend(computed.sources)
        result.limitations.extend(computed.limitations)
        local.update({e.id:e.model_dump() for e in computed.evidence})
    return result
