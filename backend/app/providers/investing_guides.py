"""Bounded public investor-education sources, not current market or tax advice."""
from bs4 import BeautifulSoup
from pydantic import Field
from typing import Literal
from app.schemas import Model, Evidence, Source, ToolResult
from app.providers.research_sources import public_get, identity

GUIDES={
 'diversification':'https://www.investor.gov/introduction-investing/getting-started/asset-allocation',
 'stocks':'https://www.investor.gov/introduction-investing/investing-basics/investment-products/stocks',
 'bonds':'https://www.investor.gov/introduction-investing/investing-basics/investment-products/bonds-or-fixed-income-products/bonds',
 'funds':'https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/characteristics-mutual-funds-exchange-traded-funds',
}
class GuideArgs(Model):
    topic: Literal['diversification','stocks','bonds','funds']='diversification'


def investing_guide(args):
    url=GUIDES[args.topic]
    soup=BeautifulSoup(public_get(url),'html.parser')
    main=soup.select_one('article .field--name-body, article .article-body') or soup.find('article') or soup.find('main')
    if main is None:raise ValueError('No identifiable educational content')
    for tag in main(['script','style','nav','footer','header']):tag.decompose()
    blocks=list(dict.fromkeys(' '.join(p.get_text(' ',strip=True).split()) for p in main.find_all(['p','li','td'])))
    blocks=[p for p in blocks if 70<=len(p)<=2000][:12]
    sid=identity('guide',url)
    return ToolResult(status='ok' if blocks else 'no_data',sources=[Source(id=sid,title='Investor.gov: '+args.topic,uri=url,synthetic=False)],evidence=[Evidence(id=f'{sid}:{i}',source_id=sid,ticker='GENERAL',text=text,scope='unknown') for i,text in enumerate(blocks)],limitations=['Investor education excerpts only; not current prices, personalized advice, tax guidance or exhaustive coverage.'])
