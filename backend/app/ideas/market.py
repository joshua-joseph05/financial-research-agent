"""Dated market snapshots; no live-quote or fair-value claims."""
import json
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from app.providers.research_sources import public_get, identity
from app.schemas import Evidence, Source


def snapshot(symbol, benchmark=False, now=None):
    now=now or datetime.now(timezone.utc)
    symbol=symbol.replace('.','-')
    url=f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=3mo'
    payload=json.loads(public_get(url))
    result=payload['chart']['result'][0]
    meta=result['meta']
    expected='ETF' if benchmark else 'EQUITY'
    if meta.get('symbol','').upper()!=symbol or meta.get('instrumentType')!=expected:
        raise ValueError('Returned market instrument does not match')
    currency=meta['currency']; zone=ZoneInfo(meta['exchangeTimezoneName'])
    prices=[]
    for stamp,close in zip(result.get('timestamp',[]),result['indicators']['quote'][0].get('close',[])):
        if close is None: continue
        date=datetime.fromtimestamp(stamp,timezone.utc)
        value=Decimal(str(close))
        if date.astimezone(zone).date()<now.astimezone(zone).date() and date<=now and value.is_finite() and value>0:
            prices.append((date,value))
    prices=sorted(dict(prices).items())
    if not prices: raise ValueError('No completed daily session found')
    date,close=prices[-1]
    age=(now-date).total_seconds()/86400
    session=date.astimezone(zone).date().isoformat()
    fresh=age<=7
    moves={}
    for sessions in (5,20):
        if len(prices)>sessions:
            start,base=prices[-sessions-1]
            change=(close/base-1)*100
            moves[f'{sessions}_sessions']={'percent':str(change.quantize(Decimal('0.01'))),'from':start.astimezone(zone).date().isoformat(),'to':session}
    sid=identity('ideas_market',url+session+str(close))
    text=f'{symbol}: prior-session close {close} {currency}, session {session}; retrieved {now.isoformat()}. '
    text+=' '.join(f"Change across {key.replace('_',' ')}: {row['percent']}% from {row['from']} to {row['to']}." for key,row in moves.items())
    text+=' Price change is not a valuation estimate. Raw-close adjustment basis is unverified; splits/dividends can distort price changes.'
    return {'symbol':symbol,'close':str(close),'currency':currency,'session':session,'retrieved_at':now.isoformat(),'fresh':fresh,'moves':moves,
            'evidence':Evidence(id=sid,source_id=sid,ticker=symbol,text=text,metric='market_close',value=str(close),unit=currency).model_dump(),
            'source':Source(id=sid,title=f'{symbol} public daily chart, session {session}',uri=url,synthetic=False).model_dump()}
