from datetime import datetime,timezone,timedelta
import json
import pytest
from app.providers import sentiment_sources as s

NOW=datetime.now(timezone.utc)
DATE=NOW.isoformat()
ROW={'id':'one','url':'https://example.com/story','title':'Example','published':DATE,'publisher':'Example','date_source':'search_feed'}

def html(text='Microsoft faces growing competition. '*25,meta=None):
    return ('<html><script type="application/ld+json">'+json.dumps(meta or {'@type':'NewsArticle','datePublished':DATE,'publisher':{'name':'Original Publisher'},'author':{'name':'Jane Doe'}})+'</script><article><p>'+text+'</p></article></html>').encode()

@pytest.mark.parametrize('url',['http://example.com/a','https://localhost/a','https://127.0.0.1/a','https://169.254.169.254/a','https://[::1]/a','https://user@example.com/a','https://example.com:444/a','https://foo.internal/a'])
def test_rejects_nonpublic_or_credential_urls(url):assert not s.safe_url(url)

def test_allows_new_public_publishers_without_fixed_allowlist():assert s.safe_url('https://new-publisher.example.com/story')

def test_dns_private_answers_rejected(monkeypatch):
    monkeypatch.setattr(s.socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('10.0.0.1',443))])
    with pytest.raises(ValueError,match='Non-public'):s.public_addresses('example.com')

def test_public_connection_is_pinned_and_tls_verifies_host(monkeypatch):
    called=[]
    class Context:
        def wrap_socket(self,sock,server_hostname):called.append(server_hostname);return sock
    conn=s.PinnedHTTPS('example.com','93.184.216.34',3);conn._context=Context()
    monkeypatch.setattr(s.socket,'create_connection',lambda dest,timeout:called.append(dest) or object())
    conn.connect()
    assert called==[('93.184.216.34',443),'example.com']

def test_redirect_to_private_destination_rejected(monkeypatch):
    monkeypatch.setattr(s,'public_addresses',lambda host:['93.184.216.34'])
    class Response:
        status=302
        def getheader(self,key,default=''):return 'https://127.0.0.1/private'
    class Connection:
        def __init__(self,*args):pass
        def request(self,*args,**kwargs):pass
        def getresponse(self):return Response()
        def close(self):pass
    monkeypatch.setattr(s,'PinnedHTTPS',Connection)
    with pytest.raises(ValueError,match='Unsafe'):s.fetch('https://example.com')

def test_article_metadata_and_accessible_body():
    r=s.extract(ROW,html(),ROW['url'])
    assert r['publisher']=='Original Publisher'
    assert r['author']=='Jane Doe'
    assert r['date_source']=='article_metadata'
    assert 'Microsoft' in r['body']

@pytest.mark.parametrize('date',[(NOW-timedelta(days=90)).isoformat(),(NOW+timedelta(days=1)).isoformat(),'nonsense'])
def test_missing_stale_future_article_dates_rejected(date):
    with pytest.raises(ValueError):s.extract({**ROW,'published':''},html(meta={'@type':'NewsArticle','datePublished':date}),ROW['url'])

def test_metadata_does_not_substitute_for_missing_body():
    with pytest.raises(ValueError):s.extract(ROW,b'<html><p>Please log in</p></html>',ROW['url'])

def test_paywall_marked_article_rejected():
    with pytest.raises(ValueError):s.extract(ROW,html(meta={'@type':'NewsArticle','datePublished':DATE,'isAccessibleForFree':False}),ROW['url'])

def test_tracking_and_redirect_wrappers_deduplicate():
    assert s.unwrap('http://www.bing.com/news/apiclick.aspx?url=https%3A%2F%2Fexample.com%2Fa%3Futm_source%3Dx')=='https://example.com/a'
    assert s.canonical('https://example.com/a?utm_source=x#heading')=='https://example.com/a'

def test_syndicated_body_detected_across_publishers():
    assert s.duplicate({'body':'One two three four five six seven eight nine ten.'},[{'id':'old','body':'One two three four five six seven eight nine ten. Extra ending.'}])=='old'

def test_search_provider_failure_does_not_hide_other_results(monkeypatch):
    def fetch(url,deadline):
        if 'bing.com' in url:raise ValueError('Unavailable')
        if 'duckduckgo' in url:return b'<div class="result"><a class="result__a" href="https://other.com/story">Microsoft outlook</a></div>',url
        return f'<rss><channel><item><link>https://example.com/story</link><title>Microsoft</title><pubDate>{NOW.strftime("%a, %d %b %Y %H:%M:%S +0000")}</pubDate></item></channel></rss>'.encode(),url
    monkeypatch.setattr(s,'fetch',fetch)
    result=s.discover('MSFT','Microsoft')
    assert len(result['candidates'])==2
    assert sum(a['status']=='unavailable' for a in result['attempts'])==2


def test_syndication_metadata_keeps_original_provider():
    meta={'@type':'NewsArticle','datePublished':DATE,'publisher':{'name':'Hosting Portal'},'provider':{'name':'Original Reporting Outlet'}}
    assert s.extract(ROW,html(meta=meta),ROW['url'])['publisher']=='Original Reporting Outlet'


def test_obviously_unrelated_feed_items_are_filtered(monkeypatch):
    def fetch(url,deadline):
        if 'yahoo' not in url:raise ValueError('Unavailable')
        return b'<rss><channel><item><link>https://example.com/msft</link><title>Microsoft stock outlook</title></item><item><link>https://other.com/ibm</link><title>IBM earnings</title></item></channel></rss>',url
    monkeypatch.setattr(s,'fetch',fetch)
    result=s.discover('MSFT','Microsoft Corporation')
    assert [v['title'] for v in result['candidates'].values()]==['Microsoft stock outlook']


def test_fetch_rejects_oversized_response(monkeypatch):
    monkeypatch.setattr(s,'public_addresses',lambda host:['93.184.216.34'])
    class Response:
        status=200
        def getheader(self,key,default=''):return 'text/html'
        def read(self,size):return b'x'*65536
    class Connection:
        def __init__(self,*args):pass
        def request(self,*args,**kwargs):pass
        def getresponse(self):return Response()
        def close(self):pass
    monkeypatch.setattr(s,'PinnedHTTPS',Connection)
    with pytest.raises(ValueError,match='size limit'):s.fetch('https://example.com')
