"""Free SEC data, cached only for the lifetime of this research run."""
import hashlib
import re
import time
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

from app.schemas import Evidence, Source, ToolResult
from app.providers.filing_context import ContextualFiling


def rank_passages(paragraphs, query):
    """Length-normalized lexical ranking; phrases distinguish matching financial terms."""
    stop = {'the', 'and', 'for', 'with', 'what', 'why', 'how', 'have', 'has', 'were', 'was', 'are', 'factors', 'drivers'}
    tokens = [w for w in re.findall(r'[a-z]+', query.lower()) if len(w) > 2 and w not in stop]
    terms = set(tokens)
    phrases = {' '.join(tokens[i:i+2]) for i in range(len(tokens)-1)}
    def score(item):
        text = item[1].lower()
        words = re.findall(r'[a-z]+', text)
        hits = sum(min(words.count(term), 3) for term in terms)
        phrase_hits = sum(phrase in text for phrase in phrases)
        historical = bool(set(tokens) & {'change', 'changes', 'changed', 'explanation', 'explain', 'increased', 'decreased'})
        if historical:
            # Query expansion retrieves reported outcomes rather than only prospective risks.
            if 'operating' in terms and 'margin' in terms and 'operating income' in text:
                phrase_hits += 2
            outcome = bool(re.search(r'\b(increased|decreased|grew|declined)\b', text))
            cause = bool(re.search(r'\b(driven|due to|because|reflecting)\b', text))
            hits += 8 * outcome + 5 * (outcome and cause)
            if not outcome and re.search(r'\b(may|could|might)\b', text):
                hits *= 0.25
                phrase_hits *= 0.25
        return (hits + 4 * phrase_hits) / (1 + len(words) / 100)
    return sorted(enumerate(paragraphs), key=score, reverse=True)


def annual_facts(payload, ticker, cik, years=2, metrics=None):
    """Select whole-year USD facts by actual duration; never infer quarters from YTD."""
    tags = {'revenue': ['RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet'],
            'operating_income': ['OperatingIncomeLoss'],
            'net_income': ['NetIncomeLoss'],
            'operating_cash_flow': ['NetCashProvidedByUsedInOperatingActivities'],
            'capital_expenditure': ['PaymentsToAcquirePropertyPlantAndEquipment']}
    tags = {key: tags[key] for key in (metrics or ['revenue', 'operating_income'])}
    candidates = {}
    for metric, concepts in tags.items():
        for priority, concept in enumerate(concepts):
            rows = payload.get('facts', {}).get('us-gaap', {}).get(concept, {}).get('units', {}).get('USD', [])
            for row in rows:
                try:
                    if isinstance(row.get('val'), bool) or not Decimal(str(row['val'])).is_finite():
                        continue
                    start, end = date.fromisoformat(row['start']), date.fromisoformat(row['end'])
                    duration = (end - start).days + 1
                    if not 350 <= duration <= 380 or row['form'] not in ('10-K', '10-K/A'):
                        continue
                    if date.fromisoformat(row['filed']) > date.today():
                        continue
                    key = (metric, row['start'], row['end'])
                    rank = (row['filed'], row['accn'], -priority)
                    if key not in candidates or rank > candidates[key][0]:
                        candidates[key] = (rank, row, concept)
                except (KeyError, ValueError, TypeError, InvalidOperation):
                    continue
    # Choose shared exact windows to avoid pairing different fiscal calendars.
    windows = sorted({(s, e) for m, s, e in candidates
                      if all((metric, s, e) in candidates for metric in tags)}, key=lambda p: p[1])[-years:]
    evidence, sources = [], {}
    for start, end in windows:
        for metric in tags:
            _, row, concept = candidates[(metric, start, end)]
            accession = row['accn']
            sid = f'sec:{cik}:{accession}'
            uri = f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace("-", "")}/{accession}-index.html'
            sources[sid] = Source(id=sid, title=f'{ticker} {row["form"]}, filed {row["filed"]}', uri=uri,
                                 synthetic=False, accession=accession, filed=row['filed'])
            eid = 'secfact:' + hashlib.sha256(f'{sid}:{concept}:{start}:{end}'.encode()).hexdigest()[:12]
            evidence.append(Evidence(id=eid, source_id=sid, ticker=ticker, metric=metric,
                value=str(row['val']), unit='USD', period=end, period_start=start, period_end=end,
                period_type='annual', concept=f'us-gaap:{concept}', scope='company',
                text=f'{ticker} annual {metric}, {start} through {end}: {row["val"]} USD. '
                     f'Reported in {row["form"]} filed {row["filed"]}; concept us-gaap:{concept}.'))
    return ToolResult(status='ok' if evidence else 'no_data', evidence=evidence, sources=list(sources.values()),
        limitations=['Annual consolidated USD standard-tag facts only; quarterly, YTD, segment and custom-tag facts are not supported. Latest filed values for each exact fiscal window are used; comparative figures may be restated.',
                     'Companyfacts is SEC-extracted XBRL; figures have not been independently reconciled against the rendered filing tables.'])


class SECClient:
    def __init__(self, user_agent, transport=None):
        if not user_agent or '@' not in user_agent:
            raise ValueError('Set SEC_USER_AGENT to an application name and contact email before using SEC data.')
        self.client = httpx.Client(headers={'User-Agent': user_agent, 'Accept-Encoding': 'gzip, deflate'},
                                   timeout=20, follow_redirects=False, transport=transport)
        self.cache = {}
        self.last_request = 0.0

    def close(self):
        self.client.close()

    def get(self, url, json=True):
        if url not in self.cache:
            time.sleep(max(0, 0.5 - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            response = self.client.get(url)
            response.raise_for_status()
            if len(response.content) > 25_000_000:
                raise ValueError('SEC response exceeds the V1 size limit')
            self.cache[url] = response
        response = self.cache[url]
        return response.json() if json else response.text

    def resolve(self, requested):
        rows = self.get('https://www.sec.gov/files/company_tickers.json').values()
        query = requested.strip().upper()
        matches = [r for r in rows if r['ticker'].upper() == query or r['title'].upper() == query]
        if len(matches) != 1:
            raise ValueError('Company not uniquely resolved. Supply its exact SEC-listed ticker.')
        row = matches[0]
        return row['ticker'], str(row['cik_str']).zfill(10), row['title']

    def execute(self, name, args):
        ticker, cik, title = self.resolve(args.ticker)
        if name == 'get_financials':
            return annual_facts(self.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json'), ticker, cik)
        url = f'https://data.sec.gov/submissions/CIK{cik}.json'
        submissions = self.get(url)
        if name == 'get_company_profile':
            sid = f'sec:profile:{cik}'
            return ToolResult(status='ok', sources=[Source(id=sid, title=f'SEC issuer identity: {title}', uri=url, synthetic=False)],
                evidence=[Evidence(id=sid, source_id=sid, ticker=ticker,
                    text=f'{submissions["name"]} ({ticker}), CIK {cik}. SIC industry: {submissions.get("sicDescription", "unavailable")}.')])
        recent = submissions.get('filings', {}).get('recent', {})
        indices = [i for i, form in enumerate(recent.get('form', [])) if form in ('10-K', '10-K/A')][:2]
        query = getattr(args, 'query', None)
        section = getattr(args, 'section', None)
        if section and section not in ('business', 'risks', 'md&a'):
            raise ValueError('Supported section topics: business, risks, md&a')
        # Topic retrieval, not a claim that headings or entire sections were extracted.
        query = query or {'business': 'products services customers', 'risks': 'growth demand competition supply export restrictions customers',
                          'md&a': 'operating income margin revenue expenses depreciation'}.get(section, 'operating income revenue risk')
        words = {w for w in re.findall(r'[a-z]+', query.lower()) if len(w) > 2}
        evidence, sources = [], []
        for index in indices:
            accession = recent['accessionNumber'][index]
            document = recent['primaryDocument'][index]
            if not re.fullmatch(r'[\w.\-]+', document) or not re.fullmatch(r'\d{10}-\d{2}-\d{6}', accession):
                continue
            uri = f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace("-", "")}/{document}'
            parser = ContextualFiling()
            parser.feed(self.get(uri, json=False))
            passages = parser.passages()
            if section:
                passages = [p for p in passages if p.section == section]
            requested_scope = getattr(args, 'scope', 'all')
            if requested_scope != 'all':
                passages = [p for p in passages if p.scope == requested_scope]
            fiscal_year = getattr(args, 'fiscal_year', None)
            if fiscal_year:
                passages = [p for p in passages if p.fiscal_years and p.fiscal_years[0] == fiscal_year]
            ranked = rank_passages([p.text for p in passages], query)
            sid = f'sec:{cik}:{accession}'
            sources.append(Source(id=sid, title=f'{ticker} {recent["form"][index]}, filed {recent["filingDate"][index]}',
                                  uri=uri, synthetic=False, accession=accession, filed=recent['filingDate'][index]))
            report_dates = recent.get('reportDate', [])
            report_period = report_dates[index] if index < len(report_dates) else None
            chosen, seen_headings = [], set()
            for position, paragraph in ranked:
                if not any(w in paragraph.lower() for w in words):
                    continue
                heading = tuple(passages[position].headings)
                if section == 'risks':
                    if re.search(r'following risk factors should be considered|following risks could harm', paragraph, re.I):
                        continue
                    if heading and heading in seen_headings:
                        continue
                chosen.append((position, paragraph))
                seen_headings.add(heading)
                if len(chosen) == 4:
                    break
            for position, paragraph in chosen:
                if not any(w in paragraph.lower() for w in words):
                    continue
                passage = passages[position]
                context = f"Scope: {passage.scope}; segment: {passage.segment or 'none/unknown'}; comparison fiscal years: {passage.fiscal_years or 'unknown'}; headings: {' > '.join(passage.headings) or 'unknown'}"
                digest = hashlib.sha256((paragraph + context).encode()).hexdigest()[:12]
                evidence.append(Evidence(id=f'passage:{hashlib.sha256((sid + digest).encode()).hexdigest()[:12]}', source_id=sid, ticker=ticker,
                    scope=passage.scope, segment=passage.segment, fiscal_years=passage.fiscal_years,
                    section=passage.section, headings=passage.headings, report_period=report_period,
                    text=f'Filing {accession}, report period {report_period or "unknown"}, paragraph {passage.offset}. '
                         f'{context}. Excerpt: {paragraph[:2200]}'
                         + (' [passage truncated]' if len(paragraph) > 2200 else '')))
        recovery = []
        if not evidence and (getattr(args, 'scope', 'all') != 'all' or getattr(args, 'fiscal_year', None)):
            recovery.append('No passages matched the scope/year filters. This does not establish absence of evidence. Retry with scope=all and no fiscal_year; for prospective risks use section=risks. Unknown comparison headings do not invalidate a disclosed risk.')
        return ToolResult(status='ok' if evidence else 'no_data', evidence=evidence, sources=sources,
            limitations=recovery + ['Bounded filing excerpts with conservatively parsed headings and explicit fiscal comparisons; unknown scope or comparison years cannot support historical causal attribution. Heading formats vary, coverage is not exhaustive, and report dates are not paragraph comparison dates. No quarterly filings, transcripts, news or market prices.'])
