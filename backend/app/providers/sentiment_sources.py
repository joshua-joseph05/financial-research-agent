"""Free multi-index discovery and bounded public-article extraction.

Discovered URLs only; all DNS answers and each redirect are checked. Connections
are pinned to a validated public address while TLS verifies the original hostname.
No browser cookies, credentials, proxies, paywall workarounds or paid services.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

MAX_BYTES = 2_000_000
TRACKING = {'guccounter', 'guce_referrer', 'guce_referrer_sig', '.tsrc', 'ref', 'source', 'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'gclid', 'fbclid'}


def safe_url(url):
    try:
        p = urlsplit(url)
        host = (p.hostname or '').lower()
        if p.scheme != 'https' or p.port not in (None, 443) or p.username or p.password or not host or host.endswith(('.local', '.localhost', '.internal')) or host == 'localhost':
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return '.' in host and re.fullmatch(r'[a-z0-9.-]+', host) is not None
    except ValueError:
        return False


def canonical(url):
    p = urlsplit(url)
    query = urlencode([(k, v) for k, v in parse_qsl(p.query) if k.lower() not in TRACKING and not k.lower().startswith('utm_')])
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or '/', query, ''))


def public_addresses(host):
    addresses = list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise ValueError('Non-public destination')
    return addresses


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


def fetch(url, deadline=None):
    end = min(deadline or time.monotonic()+20, time.monotonic()+20)
    for _ in range(4):
        if not safe_url(url):
            raise ValueError('Unsafe public URL')
        p = urlsplit(url)
        addresses = public_addresses(p.hostname)
        remaining = end-time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Article retrieval deadline')
        connection = PinnedHTTPS(p.hostname, addresses[0], min(10, remaining))
        try:
            connection.request('GET', urlunsplit(('', '', p.path or '/', p.query, '')), headers={'User-Agent': 'FinancialResearchAgent/0.2', 'Accept': 'text/html,application/rss+xml,application/xml;q=0.9,*/*;q=0.5', 'Accept-Encoding': 'identity'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                url = urljoin(url, response.getheader('Location', ''))
                continue
            if response.status != 200:
                raise ValueError(f'HTTP {response.status}')
            content_type = response.getheader('Content-Type', '').lower()
            if not any(t in content_type for t in ('html', 'xml', 'text/plain')):
                raise ValueError('Unsupported content type')
            chunks, size = [], 0
            while True:
                if time.monotonic() >= end:
                    raise TimeoutError('Article retrieval deadline')
                chunk = response.read(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError('Source exceeds size limit')
                chunks.append(chunk)
            return b''.join(chunks), canonical(url)
        finally:
            connection.close()
    raise ValueError('Too many redirects')


def timestamp(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except (ValueError, TypeError):
        try:
            result = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None
    # A date without a timezone is retained as an explicit UTC date assumption.
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def in_window(value, days, now=None):
    stamp = timestamp(value)
    return stamp is not None and (now or datetime.now(timezone.utc))-timedelta(days=days) <= stamp <= (now or datetime.now(timezone.utc))


def unwrap(url):
    if url.startswith('//'):
        url = 'https:'+url
    p = urlsplit(url)
    if p.hostname in ('www.bing.com', 'bing.com'):
        url = parse_qs(p.query).get('url', [url])[0]
    elif p.hostname in ('duckduckgo.com', 'www.duckduckgo.com'):
        url = parse_qs(p.query).get('uddg', [url])[0]
    return canonical(url)


def row(url, title, published, provider, snippet='', publisher=''):
    url = unwrap(url)
    if not safe_url(url):
        return None
    return {'id': 'article:'+hashlib.sha256(url.encode()).hexdigest()[:16], 'url': url, 'title': title[:400], 'published': published or '', 'date_source': 'search_feed' if published else 'unknown', 'publisher': publisher or urlsplit(url).hostname, 'discovered_via': [provider], 'snippet': BeautifulSoup(snippet, 'html.parser').get_text(' ', strip=True)[:600]}


def parse_feed(body, provider, days):
    root = ET.fromstring(body)
    result = []
    for item in root.findall('./channel/item')[:40]:
        pub = item.findtext('pubDate', '')
        if pub and not in_window(pub, days):
            continue
        source = next((child.text for child in item if child.tag.rsplit('}', 1)[-1].lower() == 'source'), '')
        item_row = row(item.findtext('link', ''), item.findtext('title', ''), timestamp(pub).isoformat() if timestamp(pub) else '', provider, item.findtext('description', ''), source)
        if item_row:
            result.append(item_row)
    return result


def discover(ticker, company, query='', days=30, deadline=None):
    # Every search remains company-scoped; the model supplies topics, not URLs.
    name = re.sub(r'\b(?:CORPORATION|CORP|INCORPORATED|INC|LTD)\.?\b', '', company, flags=re.I).strip(' ,') or company
    scoped = f'"{name}" {ticker} stock {query or "outlook risks investment arguments"}'
    urls = {
        'yahoo_finance': 'https://feeds.finance.yahoo.com/rss/2.0/headline?'+urlencode({'s': ticker, 'region':'US', 'lang':'en-US'}),
        'bing_news': 'https://www.bing.com/news/search?'+urlencode({'q': scoped, 'format':'rss'}),
        'bing_web': 'https://www.bing.com/search?'+urlencode({'q': scoped, 'format':'rss'}),
        'duckduckgo_web': 'https://html.duckduckgo.com/html/?'+urlencode({'q': scoped, 'df':'m'}),
    }
    def one(item):
        provider, url = item
        try:
            body, _ = fetch(url, deadline)
            if provider != 'duckduckgo_web':
                rows = parse_feed(body, provider, days)
            else:
                soup = BeautifulSoup(body, 'html.parser')
                rows = []
                for result in soup.select('.result')[:20]:
                    anchor = result.select_one('.result__a')
                    snippet = result.select_one('.result__snippet')
                    if anchor:
                        value = row(anchor.get('href', ''), anchor.get_text(' ', strip=True), '', provider, snippet.get_text(' ',strip=True) if snippet else '')
                        if value: rows.append(value)
            return rows, {'provider':provider,'status':'ok' if rows else 'no_results','candidates':len(rows)}
        except Exception as error:
            return [], {'provider':provider,'status':'unavailable','error':type(error).__name__}
    catalog, attempts = {}, []
    with ThreadPoolExecutor(max_workers=4) as executor:
        for rows, attempt in executor.map(one, urls.items()):
            attempts.append(attempt)
            for value in rows:
                if value['id'] in catalog:
                    existing = catalog[value['id']]
                    existing['discovered_via'] = sorted(set(existing['discovered_via']+value['discovered_via']))
                    if not existing['published'] and value['published']: existing.update(published=value['published'],date_source=value['date_source'])
                else: catalog[value['id']] = value
    # A company feed can contain broad market stories; discard obvious nonmatches.
    def relevance(value):
        title=value['title'].casefold();snippet=value.get('snippet','').casefold()
        company_match=lambda text: name.casefold() in text or (len(ticker)>=3 and re.search(r'(?<![a-z0-9])'+re.escape(ticker.casefold())+r'(?![a-z0-9])',text))
        return 2 if company_match(title) else 1 if company_match(snippet) else 0
    catalog={key:value for key,value in catalog.items() if relevance(value)}
    catalog=dict(sorted(catalog.items(),key=lambda pair:relevance(pair[1]),reverse=True))
    # Round-robin hosts prevents the first index or one portal consuming all slots.
    groups = {}
    for value in catalog.values(): groups.setdefault(urlsplit(value['url']).hostname, []).append(value)
    selected = {}
    while groups and len(selected)<36:
        for host in list(groups):
            value=groups[host].pop(0);selected[value['id']]=value
            if not groups[host]:del groups[host]
            if len(selected)>=36:break
    return {'candidates':selected,'attempts':attempts}


def metadata(soup):
    objects=[]
    def visit(node):
        if isinstance(node,list):
            for item in node:visit(item)
        elif isinstance(node,dict):
            kind=node.get('@type',[])
            if isinstance(kind,str):kind=[kind]
            if any(k in ('NewsArticle','Article','BlogPosting','ReportageNewsArticle','AnalysisNewsArticle','OpinionNewsArticle') for k in kind):objects.append(node)
            if '@graph' in node:visit(node['@graph'])
    for script in soup.find_all('script',type='application/ld+json'):
        try:visit(json.loads(script.string or script.get_text()))
        except (ValueError,TypeError):continue
    return objects[0] if objects else {}


def names(value):
    if isinstance(value,dict):return str(value.get('name',''))
    if isinstance(value,list):return ', '.join(filter(None,(names(v) for v in value)))
    return value if isinstance(value,str) else ''


def extract(candidate, body, final_url, days=30):
    soup=BeautifulSoup(body,'html.parser');meta=metadata(soup)
    def tag(*keys):
        for key in keys:
            item=soup.find('meta',attrs={'property':key}) or soup.find('meta',attrs={'name':key})
            if item and item.get('content'):return item['content']
        return ''
    pub=meta.get('datePublished') or tag('article:published_time','datePublished','pubdate') or candidate.get('published','')
    if not in_window(pub,days):raise ValueError('Article publication date missing, future, or outside window')
    if meta.get('isAccessibleForFree') in (False,'false'):raise ValueError('Article marked restricted')
    author=names(meta.get('author')) or tag('author')
    publisher=names(meta.get('provider')) or names(meta.get('publisher')) or candidate.get('publisher') or urlsplit(final_url).hostname
    # Yahoo is a syndication host: use a visible provider attribution when present.
    if urlsplit(final_url).hostname=='finance.yahoo.com':
        provider=soup.select_one('.caas-attr-provider')
        if provider:publisher=provider.get_text(' ',strip=True) or publisher
    title=meta.get('headline') or tag('og:title') or candidate['title']
    for node in soup(['script','style','nav','footer','aside','form','header']):node.decompose()
    blocks=[]
    for selector in ['.caas-body','[itemprop="articleBody"]','.article-body','.article-content','.entry-content','.post-content','article','main']:
        for container in soup.select(selector):
            paras=[p.get_text(' ',strip=True) for p in container.find_all(['p','h2','h3','li'])]
            text='\n'.join(dict.fromkeys(p for p in paras if len(p)>30))
            if len(text)>=400:blocks.append(text)
        if blocks:break
    if not blocks:raise ValueError('Accessible article body unavailable')
    text=max(blocks,key=len)[:18000]
    if any(marker in text[:500].lower() for marker in ['enable javascript and cookies to continue','verify you are human','sign in to continue reading','subscribe to continue reading']):raise ValueError('Access interstitial')
    return {**candidate,'url':final_url,'title':str(title)[:400],'published':timestamp(pub).isoformat(),'date_source':'article_metadata' if meta.get('datePublished') or tag('article:published_time','datePublished','pubdate') else candidate.get('date_source','search_feed'),'publisher':publisher[:200],'author':author[:200],'body':text,'truncated':len(max(blocks,key=len))>18000}


def read(candidate, days=30, deadline=None):
    body, final_url=fetch(candidate['url'],deadline)
    return extract(candidate,body,final_url,days)


def duplicate(article, previous):
    def shingles(text):
        words=re.findall(r'\w+',text.lower())
        return {' '.join(words[i:i+5]) for i in range(max(0,len(words)-4))}
    current=shingles(article['body'])
    for other in previous:
        old=shingles(other['body'])
        if current and old and len(current&old)/min(len(current),len(old))>=.75:return other['id']
    return None
