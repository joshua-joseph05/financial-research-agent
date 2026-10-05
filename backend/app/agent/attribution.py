"""Deterministic attribution checks supplement, rather than replace, claim review."""


def attribution_issue(finding, observations):
    passages = [observations[key] for key in finding['evidence_ids']
                if key in observations and key.startswith('passage:')]
    if not passages:
        if finding.get('explains_change') and not any(':section:' in key for key in finding['evidence_ids']):
            return 'A historical explanation requires a filing passage, not only numbers or calculations'
        return None
    import re
    if re.search(r"\b(?:and|or|a|an|the|higher|lower|in|of|to)[.!?]?$", finding['text'].strip(), re.I):
        return 'Incomplete claim sentence; write a shorter complete statement rather than a truncated list'
    for passage in passages:
        if finding.get('scope') != passage.get('scope', 'unknown'):
            return 'Claim scope must match the cited passage; segment results cannot be promoted to company results'
        if finding.get('segment') != passage.get('segment'):
            return 'Claim segment must match the cited passage; split claims about different segments'
        if finding.get('fiscal_years', []) != passage.get('fiscal_years', []):
            return 'Claim comparison years must match the passage heading; split claims about different periods'
    if finding.get('explains_change'):
        if finding.get('kind') == 'risk':
            return 'A hypothetical risk is not a historical explanation'
        if finding.get('scope') == 'unknown' or len(finding.get('fiscal_years', [])) != 2:
            return 'Unknown scope or comparison period cannot establish a historical explanation'
    return None


def explanation_gaps(state, findings):
    if 'filing_explanations' not in state['plan'].get('evidence_requirements', []):
        return []
    observations = state['observations']
    periods = {}
    for record in observations.values():
        if record.get('value') is not None and not record.get('operation') and record.get('period_end'):
            periods.setdefault(record['ticker'], set()).add(record['period_end'])
    if not periods:
        return ['Retrieve annual financial periods before attributing historical explanations']
    gaps = []
    for ticker, dates in periods.items():
        dates = sorted(dates, reverse=True)[:2]
        # Only an exact match of explicit comparison labels is accepted here.
        # Nonstandard fiscal-year labeling remains unresolved rather than guessed.
        years = [int(value[:4]) for value in dates]
        matches = []
        for finding in findings:
            if not finding.get('explains_change') or finding.get('scope') != 'company':
                continue
            if finding.get('fiscal_years') != years or len(years) != 2:
                continue
            cited = [observations[key] for key in finding['evidence_ids'] if key.startswith('passage:') and key in observations]
            if cited and all(e['ticker'] == ticker for e in cited) and not attribution_issue(finding, observations):
                matches.append(finding)
        if not matches:
            gaps.append(f'{ticker}: missing a supported company-wide explanation explicitly attributed to comparison years {years}; retrieve company-scope filing passages for that comparison. Segment, older-period, and unknown-context passages are background only.')
    return gaps


def render_findings(findings, observations, historical_explanation=True):
    """No new free-text summary claims after verification. Preserve claim qualifiers."""
    parts = []
    for finding in findings:
        text = finding['text']
        for key in observations:
            text = text.replace('[' + key + ']', '')
        labels = []
        cited_passages = [observations[key] for key in finding['evidence_ids'] if key.startswith('passage:') and key in observations]
        for ticker in {e['ticker'] for e in cited_passages}:
            dates = sorted({e['period_end'] for e in observations.values() if e.get('ticker') == ticker and e.get('period_end') and not e.get('operation')}, reverse=True)[:2]
            if historical_explanation and finding.get('kind') != 'risk' and len(dates) == 2 and (finding.get('scope') != 'company' or finding.get('fiscal_years') != [int(d[:4]) for d in dates]):
                labels.append('Background only; not the company comparison being explained')
                break
        if finding.get('scope') == 'company':
            labels.append('Company-wide')
        elif finding.get('scope') == 'segment':
            labels.append('Business area: ' + (finding.get('segment') or 'unspecified'))
        elif finding.get('scope') == 'unknown':
            labels.append('Disclosed risk' if finding.get('kind') == 'risk' else ('Scope unverified; background only' if historical_explanation else 'Source-reported'))
        if finding.get('fiscal_years'):
            labels.append('FY ' + ' vs FY '.join(str(y) for y in finding['fiscal_years']))
        elif historical_explanation and finding.get('kind') != 'risk' and any(key.startswith('passage:') for key in finding['evidence_ids']):
            labels.append('Comparison period unverified')
        if finding.get('explains_change'):
            labels.append('Interpretation' if finding.get('kind') == 'interpretation' else 'Reported explanation')
        text = ' '.join(text.split())
        parts.append((' — '.join(labels) + ': ' if labels else '') + text)
    return '\n\n'.join(parts)


def calculation_findings(observations):
    """Verified arithmetic gets canonical prose, never LLM-rewritten dates or values."""
    from app.schemas import Finding
    from decimal import Decimal, InvalidOperation
    findings = []
    for record in observations.values():
        operation = record.get('operation')
        if not operation or len(record.get('input_ids', [])) != 2:
            continue
        inputs = [observations.get(key) for key in record['input_ids']]
        if not all(inputs):
            continue
        a, b = inputs
        if operation == 'operating_margin':
            text = f"{record['ticker']} operating margin for the annual period ending {record['period']}: {record['value']}%."
        elif operation == 'margin_change':
            text = f"{record['ticker']} operating margin changed by {record['value']} percentage points from {b['period']} to {a['period']}."
        elif operation == 'growth':
            text = f"{record['ticker']} {a['metric'].replace('_', ' ')} changed by {record['value']}% from {b['period']} to {a['period']}."
        else:
            continue
        # Show the sourced arithmetic, not just the final percentage. The
        # downstream structural check still reproduces the calculation.
        if a.get('value') is not None and b.get('value') is not None:
            unit = a.get('unit') or ''
            if operation == 'growth':
                text += f" Calculation ({unit} inputs): ({a['value']} − {b['value']}) ÷ {b['value']} = {record['value']}%."
            elif operation == 'operating_margin':
                text += f" Calculation ({unit} inputs): {a['value']} ÷ {b['value']} = {record['value']}%."
            elif operation == 'margin_change':
                text += f" Calculation: {a['value']}% − {b['value']}% = {record['value']} percentage points."
        if operation in ('growth','margin_change'):
            try:
                change=Decimal(str(record['value']))
                if not change.is_finite():continue
            except (InvalidOperation,ValueError,TypeError):continue
            text += ' This is an increase.' if change>0 else ' This is a decrease.' if change<0 else ' There is no change at the displayed precision.'
        findings.append(Finding(id='derived:' + record['id'], text=text, evidence_ids=[record['id']], scope='company').model_dump())
    return findings


def bind_attribution(finding, observations):
    """Attach source-owned labels after generation; the model need not copy them."""
    passages = [observations[key] for key in finding['evidence_ids'] if key.startswith('passage:') and key in observations]
    frames = {(p.get('scope', 'unknown'), p.get('segment'), tuple(p.get('fiscal_years', []))) for p in passages}
    if len(frames) == 1 and finding.get('scope') is None:
        scope, segment, years = next(iter(frames))
        return {**finding, 'scope': scope, 'segment': segment, 'fiscal_years': list(years)}
    return finding


def clean_citation_suffix(finding):
    """Remove only redundant, known citation IDs appended to prose by the model."""
    import re
    match = re.search(r"\s+(?:Evidence IDs?|Citations?):\s*(.+)$", finding['text'], re.I)
    if not match:
        return finding
    keys = [key.strip().rstrip('.') for key in match[1].split(',')]
    if keys and all(key in finding['evidence_ids'] for key in keys):
        return {**finding, 'text': finding['text'][:match.start()].rstrip()}
    return finding


def reported_financial_findings(observations):
    """Render exact annual reported values; no inference or fiscal-year guessing."""
    from decimal import Decimal, InvalidOperation
    from datetime import date
    from app.schemas import Finding
    labels = {'revenue':'revenue', 'operating_income':'operating income',
              'net_income':'net income', 'operating_cash_flow':'operating cash flow',
              'capital_expenditure':'capital expenditure'}
    findings=[]
    for record in observations.values():
        if (record.get('operation') or record.get('metric') not in labels
                or record.get('period_type') != 'annual'
                or record.get('scope') != 'company'
                or record.get('value') is None or not record.get('unit')
                or not record.get('ticker') or not record.get('source_id')):
            continue
        try:
            if not Decimal(str(record['value'])).is_finite():continue
            end=date.fromisoformat(record['period_end']).isoformat()
        except (ValueError, TypeError, KeyError, InvalidOperation):
            continue
        text=f"{record['ticker']} reported {labels[record['metric']]} of {record['value']} {record['unit']} for the annual period ending {end}."
        findings.append(Finding(id='derived:reported:'+record['id'],text=text,evidence_ids=[record['id']],scope='company').model_dump())
    return findings
