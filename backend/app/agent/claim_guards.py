"""Conservative checks for clear additions to a cited passage.

These reject specific contradictions or absent topics; passing is not proof of
semantic entailment. Model review and provenance checks are still required.
"""
import re

_NECESSITY = r'\b(?:necessary|required|essential|mandatory|unavoidable)\b'
_BUSINESS = re.compile(r'\b(?:earns? (?:money|revenue)|makes? money|generates? (?:revenue|sales)) (?:primarily |mainly )?(?:from|by|through)\s+(.+)',re.I)
_GENERIC = {'a','an','and','as','at','by','company','companies','for','from','in','its','it','of','on','or','providing','selling','service','services','the','their','through','to','with'}


def _asserts_necessity(text):
    return any(not re.search(r'\b(?:not|never|no longer)\s+(?:necessarily\s+)?$',text[:match.start()],re.I)
               for match in re.finditer(_NECESSITY,text,re.I))


def passage_claim_issue(text, records):
    cited=' '.join(record.get('text','') for record in records)
    if _asserts_necessity(text) and not _asserts_necessity(cited):
        return 'The cited evidence does not establish necessity; remove the requirement claim or cite evidence that establishes it'
    match=_BUSINESS.search(text)
    if match:
        # Require at least one specific business concept in the cited text,
        # not merely common words such as company, money or services. This
        # detects a business description attached to an unrelated risk passage.
        concepts={word.casefold() for word in re.findall(r'[A-Za-z]+',match.group(1)) if word.casefold() not in _GENERIC}
        cited_words={word.casefold() for word in re.findall(r'[A-Za-z]+',cited)}
        def stem(word):return word[:-1] if word.endswith('s') and len(word)>3 else word
        if concepts and not {stem(w) for w in concepts} & {stem(w) for w in cited_words}:
            return 'The cited evidence does not describe the claimed business activity; retrieve a supporting business passage'
    return None


def issuer_claim_issue(text, records, issuer_names):
    """Check explicitly named issuers against cited issuer metadata.

    This checks identity, not entity roles or semantic entailment. A passage
    explicitly naming another issuer may support a cross-company statement.
    """
    cited_tickers = {r.get('ticker') for r in records}
    cited_text = ' '.join(r.get('text', '') for r in records)
    for ticker, name in issuer_names.items():
        aliases = {ticker, name}
        short = re.sub(r'\s+(?:incorporated|corporation|corp|inc|plc|ltd|limited)\.?$', '', name, flags=re.I).strip()
        if len(short) >= 3:
            aliases.add(short)
        def mentions(value):
            return any(re.search(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', value,
                                 0 if alias == ticker else re.I)
                       for alias in aliases if alias)
        if mentions(text) and ticker not in cited_tickers and not mentions(cited_text):
            return f'The claim names {name or ticker}, but its cited evidence belongs to another issuer and does not mention that company'
    return None


def coverage_claim_issue(text):
    # Retrieval status belongs in open questions, never in a sourced company fact.
    if re.search(r'\b(?:provided |collected |available |retrieved )?(?:evidence|data|observations|sources)\s+(?:does? not|do not|doesn.t|don.t|cannot|can.t|lacks?|contains? no|provides? no|is missing|are missing)\b', text, re.I):
        return 'Retrieval coverage is not a sourced company fact; record the missing research in open_questions and check the collected evidence inventory'
    return None


def financial_trend_citation_issue(text, records):
    """Reject a stated metric trend absent from this claim's own citations.

    This is a topic-presence guard, not semantic approval or a period check.
    References to an unknown metric (for example, revenue does not establish
    cash balances) are not themselves assertions of a trend in that metric.
    """
    topics = {
        'revenue': r'revenue|sales',
        'net_income': r'net income|net profit',
        'operating_income': r'operating income|operating profit',
        'operating_cash_flow': r'operating cash flow|cash flow from operations',
        'capital_expenditure': r'capital expenditure|capital spending|capex',
        'operating_margin': r'operating margin',
    }
    cited = ' '.join(r.get('text', '') for r in records)
    metrics = {r.get('metric') for r in records}
    trend = r'(?:higher|lower|rising|falling|increasing|decreasing)'
    verb = r'(?:rose|fell|grew|increased|decreased|improved|declined)'
    for metric, names in topics.items():
        topic = rf'\b(?:{names})\b'
        asserted = re.search(rf'\b{trend}\s+{topic}|{topic}\s+(?:(?:both|also)\s+)?{verb}\b', text, re.I)
        # A reported multi-metric reference also asserts that those records
        # underlie this interpretation, even without explicit trend wording.
        reported_groups = re.findall(r'\breported\s+([^.!?;]{1,100}?)\s+(?:figures|values|results)\b', text, re.I)
        asserted = asserted or any(re.search(topic, group, re.I) for group in reported_groups)
        if asserted and metric not in metrics and not re.search(topic, cited, re.I):
            return f'The stated {metric} reference needs its own cited evidence; cite the matching metric records or remove the trend claim'
    return None
