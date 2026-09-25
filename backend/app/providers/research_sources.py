"""Free public sources with bounded retrieval and explicit provenance/limitations."""
import hashlib
import re
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode, urljoin, urlsplit
from xml.etree import ElementTree as ET

import httpx
from bs4 import BeautifulSoup
from app.schemas import Evidence, Source, ToolResult


def identity(prefix, value):
    return prefix + ':' + hashlib.sha256(value.encode()).hexdigest()[:16]


def public_get(url):
    # Never forward the SEC contact email to unrelated providers.
    with httpx.Client(timeout=20, follow_redirects=False, trust_env=False,
                      headers={'User-Agent': 'FinancialResearchAgent/0.1'}) as client:
        with client.stream('GET', url) as response:
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > 2_000_000:
                    raise ValueError('Public source response exceeds size limit')
                chunks.append(chunk)
            return b''.join(chunks)


def news(sec, args):
    ticker, _, title = sec.resolve(args.ticker)
    url = 'https://news.google.com/rss/search?' + urlencode({'q': f'"{title}" {getattr(args, "query", "")} when:{args.days}d', 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'})
    try:
        root = ET.fromstring(public_get(url))
    except ET.ParseError as error:
        raise ValueError('News provider returned invalid RSS') from error
    records, sources, seen = [], [], set()
    now = datetime.now(timezone.utc)
    for item in root.findall('./channel/item'):
        headline, link, published = (item.findtext(key, '').strip() for key in ('title', 'link', 'pubDate'))
        try:
            timestamp = parsedate_to_datetime(published)
            if timestamp.tzinfo is None:
                continue
        except (ValueError, TypeError, OverflowError):
            continue
        if not headline or not link.startswith('https://') or link in seen or not now - timedelta(days=args.days) <= timestamp <= now:
            continue
        seen.add(link)
        sid = identity('news', link)
        sources.append(Source(id=sid, title=headline[:500], uri=link, synthetic=False))
        publisher = item.findtext('source', 'Unknown publisher')
        records.append(Evidence(id=sid, source_id=sid, ticker=ticker, scope='unknown',
            text=f'UNVERIFIED NEWS HEADLINE — discovery lead only. Published {timestamp.isoformat()} by {publisher}. Headline: {headline[:700]}. Article body not retrieved; issuer relevance and underlying claims need confirmation.'))
        if len(records) >= args.limit:
            break
    return ToolResult(status='ok' if records else 'no_data', evidence=records, sources=sources,
        limitations=['Google News RSS search, not a guaranteed API; results are not exhaustive. Headlines are not verified facts and must not establish historical causes. No article bodies or paywall access.'])


def market(sec, args):
    ticker, _, _ = sec.resolve(args.ticker)
    # SEC share-class dots map to Yahoo hyphens; validate returned identity too.
    symbol = ticker.replace('.', '-')
    if not re.fullmatch(r'[A-Z0-9-]{1,20}', symbol):
        raise ValueError('Unsupported quote symbol')
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d'
    import json
    payload = json.loads(public_get(url))
    results = payload.get('chart', {}).get('result')
    if not results:
        return ToolResult(status='no_data', limitations=['Quote provider returned no chart data'])
    result = results[0]
    meta = result.get('meta', {})
    if meta.get('symbol', '').upper() != symbol or meta.get('instrumentType') != 'EQUITY':
        raise ValueError('Quote identity or instrument type does not match requested equity')
    currency, zone = meta.get('currency'), meta.get('exchangeTimezoneName')
    if not currency or not zone:
        raise ValueError('Quote currency/timezone unavailable')
    timestamps = result.get('timestamp', [])
    quotes = result.get('indicators', {}).get('quote', [])
    closes = quotes[0].get('close', []) if quotes else []
    now = datetime.now(timezone.utc)
    from zoneinfo import ZoneInfo
    local_today = now.astimezone(ZoneInfo(zone)).date()
    candidates = []
    for stamp, value in zip(timestamps, closes):
        if value is None:
            continue
        try:
            number = Decimal(str(value))
            instant = datetime.fromtimestamp(stamp, timezone.utc)
        except (ValueError, TypeError, OverflowError, InvalidOperation):
            continue
        # Exclude today's possibly unfinished daily candle; disclose the session date.
        if number.is_finite() and number > 0 and instant.astimezone(ZoneInfo(zone)).date() < local_today and instant <= now:
            candidates.append((instant, number))
    if not candidates:
        return ToolResult(status='no_data', limitations=['No completed daily-session price available in the last five days'])
    instant, value = max(candidates, key=lambda pair: pair[0])
    session = instant.astimezone(ZoneInfo(zone)).date().isoformat()
    sid = identity('market', symbol + session + str(value))
    source = Source(id=sid, title=f'{ticker} daily chart, session {session}', uri=url, synthetic=False)
    evidence = Evidence(id=sid, source_id=sid, ticker=ticker, metric='market_close', value=str(value), unit=currency,
        text=f'{ticker}: provider daily close {value} {currency} for session {session}, exchange timezone {zone}. Provider bar timestamp {instant.isoformat()}; retrieved {now.isoformat()}. Not a current executable quote; adjustment basis is not verified.')
    return ToolResult(status='ok', evidence=[evidence], sources=[source], limitations=[
        'Unofficial Yahoo public chart endpoint; access may be rate limited or unavailable. Latest available prior-session close only, not live data. No market cap, valuation ratios, or adjustment guarantees.'])


def document_url(cik, accession, filename):
    if not re.fullmatch(r'\d{10}-\d{2}-\d{6}', accession) or not re.fullmatch(r'[\w.\-]+', filename):
        raise ValueError('Invalid SEC document identifier')
    return f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace("-", "")}/{filename}'


def earnings(sec, args):
    ticker, cik, _ = sec.resolve(args.ticker)
    recent = sec.get(f'https://data.sec.gov/submissions/CIK{cik}.json').get('filings', {}).get('recent', {})
    items = recent.get('items', [])
    selected = [i for i, form in enumerate(recent.get('form', [])) if form in ('8-K', '8-K/A') and i < len(items) and '2.02' in re.split(r'[,;\s]+', items[i])][:args.limit]
    records, sources, limitations = [], [], []
    for index in selected:
        accession = recent['accessionNumber'][index]
        uri = document_url(cik, accession, recent['primaryDocument'][index])
        primary = BeautifulSoup(sec.get(uri, json=False), 'html.parser')
        documents = [(uri, primary)]
        # Follow only filing-local HTML exhibits, never arbitrary outbound links.
        prefix = uri.rsplit('/', 1)[0] + '/'
        for anchor in primary.find_all('a', href=True):
            link = urljoin(uri, anchor['href'])
            path = urlsplit(link)
            if not link.startswith(prefix) or path.query or path.fragment or not path.path.lower().endswith(('.htm', '.html')) or link == uri:
                continue
            label = anchor.get_text(' ', strip=True).lower() + ' ' + anchor['href'].lower()
            if not any(word in label for word in ('99', 'earnings', 'release')) or any(link == doc[0] for doc in documents):
                continue
            try:
                documents.append((link, BeautifulSoup(sec.get(link, json=False), 'html.parser')))
            except (httpx.HTTPError, ValueError):
                limitations.append(f'{ticker}: an earnings exhibit could not be retrieved')
            if len(documents) >= 3:
                break
        for link, soup in documents:
            for tag in soup(['script', 'style', 'ix:header']):
                tag.decompose()
            sid = identity('earnings', link)
            sources.append(Source(id=sid, title=f'{ticker} earnings announcement, filed {recent["filingDate"][index]}', uri=link, synthetic=False, accession=accession, filed=recent['filingDate'][index]))
            blocks = list(dict.fromkeys(' '.join(node.get_text(' ', strip=True).split()) for node in soup.find_all(['p', 'div'])))
            blocks = [text for text in blocks if 80 <= len(text) <= 2500 and re.search(r'\b(revenue|income|earnings|outlook|guidance|quarter|results)\b', text, re.I)]
            for text in blocks[:4]:
                eid = identity('earnings', sid + text)
                records.append(Evidence(id=eid, source_id=sid, ticker=ticker, scope='unknown',
                    text=f'Management earnings-release excerpt, filed {recent["filingDate"][index]}. Scope and fiscal comparison not independently parsed; forward-looking statements are guidance, not realized results. Excerpt: {text}'))
    return ToolResult(status='ok' if records else 'no_data', evidence=records, sources=sources,
        limitations=limitations + ['Bounded recent Item 2.02 8-K announcements and linked HTML earnings exhibits only. No transcripts, estimates, or guarantee of quarterly coverage. Filing date is not the financial period; guidance must remain forward-looking.'])


def reconcile(sec, args, observations):
    original = observations.get(args.evidence_id)
    if not original:
        raise ValueError('Choose an existing evidence ID from a financial tool')
    record = Evidence.model_validate(original)
    if record.operation or record.unit != 'USD' or not record.concept or record.period_type != 'annual':
        raise ValueError('Reconciliation requires an original annual USD SEC fact, not a calculation or market quote')
    match = re.fullmatch(r'sec:(\d{10}):(\d{10}-\d{2}-\d{6})', record.source_id)
    if not match:
        raise ValueError('Fact has no recognized SEC filing provenance')
    cik, accession = match.groups()
    ticker, resolved_cik, _ = sec.resolve(record.ticker)
    if cik != resolved_cik:
        raise ValueError('Fact issuer does not match filing provenance')
    recent = sec.get(f'https://data.sec.gov/submissions/CIK{cik}.json').get('filings', {}).get('recent', {})
    accessions = recent.get('accessionNumber', [])
    if accession not in accessions:
        return ToolResult(status='no_data', limitations=['Original filing is outside the recent submissions window; reconciliation unresolved'])
    idx = accessions.index(accession)
    uri = document_url(cik, accession, recent['primaryDocument'][idx])
    soup = BeautifulSoup(sec.get(uri, json=False), 'html.parser')
    outcome, detail = reconcile_inline(soup, record)
    sid = identity('reconciliation', record.id + uri)
    return ToolResult(status='ok', sources=[Source(id=sid, title=f'{ticker} original filing reconciliation', uri=uri, synthetic=False, accession=accession)],
        evidence=[Evidence(id=sid, source_id=sid, ticker=ticker, input_ids=[record.id], reconciliation_status=outcome,
            text=f'Reconciliation {outcome.upper()} for {record.id} ({record.metric}, {record.period_start} through {record.period_end}): {detail}')],
        limitations=['Cross-check of Companyfacts against visible table inline XBRL in the same filing, not independent audit. Unsupported transforms, dimensions, contexts and layouts remain unresolved.'])


def reconcile_inline(soup, record):
    def local(tag):
        return tag.name.split(':')[-1].lower() if tag.name else ''
    def descendants(tag, name):
        return tag.find_all(lambda t: local(t) == name)
    contexts = {}
    for context in soup.find_all(lambda t: local(t) == 'context'):
        if descendants(context, 'segment') or descendants(context, 'scenario'):
            continue
        starts, ends = descendants(context, 'startdate'), descendants(context, 'enddate')
        if starts and ends and starts[0].get_text(strip=True) == record.period_start and ends[0].get_text(strip=True) == record.period_end:
            contexts[context.get('id')] = context
    units = {unit.get('id') for unit in soup.find_all(lambda t: local(t) == 'unit') if len(descendants(unit, 'measure')) == 1 and descendants(unit, 'measure')[0].get_text(strip=True).split(':')[-1] == 'USD' and not descendants(unit, 'divide')}
    values, unsupported = set(), False
    for fact in soup.find_all('ix:nonfraction'):
        if fact.get('name') != record.concept or fact.get('contextref') not in contexts or fact.get('unitref') not in units:
            continue
        if fact.find_parent('table') is None or any(
                ancestor.name in ('ix:hidden', 'ix:header') or ancestor.has_attr('hidden') or
                re.search(r'(?:display\s*:\s*none|visibility\s*:\s*hidden)', ancestor.get('style', ''), re.I)
                for ancestor in [fact, *fact.parents] if ancestor.name):
            continue
        transform = fact.get('format', '').split(':')[-1].lower()
        if transform not in ('', 'num-dot-decimal', 'numdotdecimal') or fact.get('xsi:nil') == 'true':
            unsupported = True
            continue
        raw = fact.get_text('', strip=True).replace(',', '').replace('\u00a0', '').strip()
        if not re.fullmatch(r'-?\d+(?:\.\d+)?', raw):
            unsupported = True
            continue
        try:
            scale = int(fact.get('scale', '0'))
            if not -12 <= scale <= 12 or fact.get('sign', '') not in ('', '-'):
                raise ValueError('Unsupported scale/sign')
            value = Decimal(raw) * (Decimal(10) ** scale) * (-1 if fact.get('sign') == '-' else 1)
            values.add(value)
        except (ValueError, InvalidOperation):
            unsupported = True
    if not values or unsupported or len(values) != 1:
        return 'unresolved', 'No unique fully supported visible table fact for the exact concept, annual dates and USD unit; no match certified.'
    observed = next(iter(values))
    if observed == Decimal(record.value):
        return 'matched', f'Visible table inline XBRL equals {observed} USD after scale/sign conversion, matching the recorded {record.value} USD.'
    return 'mismatch', f'Visible table inline XBRL equals {observed} USD; Companyfacts evidence says {record.value} USD. Investigate before using the figure.'
