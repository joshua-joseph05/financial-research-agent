"""Frozen fictional financial evidence. Never used by the production routes."""
from app.schemas import Evidence, Source, ToolResult
from app.tools.registry import ToolRegistry
from app.tools.extended import EXTRA_SPECS

ROWS={'MSFT':{'revenue':[200,240],'operating_income':[60,84],'operating_cash_flow':[70,65]},'NVDA':{'revenue':[100,150],'operating_income':[30,60],'operating_cash_flow':[35,50]}}
RISKS={'MSFT':'Infrastructure investment may increase depreciation and operating costs.','NVDA':'Growth depends on a small group of customers and constrained advanced packaging supply.'}

class FixtureRegistry:
    from app.evaluation.frozen_sources import Issuers
    sec=Issuers()
    synthetic=True
    def descriptions(self,*args):
        specs=ToolRegistry().descriptions()
        return specs+[{'name':n,'description':d,'input_schema':s.model_json_schema()} for n,(s,d) in EXTRA_SPECS.items() if n=='get_financial_metric_history']
    def execute(self,call,observations):
        if call.name=='calculate_financial_metrics':return ToolRegistry().execute(call,observations)
        t=call.arguments.get('ticker')
        if t not in ROWS:return ToolResult(status='no_data',limitations=['No fixture coverage for this tool or company.'])
        source=Source(id='fixture:'+t,title='FICTIONAL EVALUATION DATA '+t,uri='https://example.invalid/fixtures/'+t,synthetic=True)
        if call.name in ('get_financials','get_financial_metric_history'):
            metrics=['revenue','operating_income'] if call.name=='get_financials' else [call.arguments.get('metric','revenue')]
            records=[]
            for metric in metrics:
                for year,value in zip([2024,2025],ROWS[t].get(metric,[])):
                    day=f'{year}-12-31'
                    records.append(Evidence(id=f'fixture:{t}:{metric}:{year}',source_id=source.id,ticker=t,text=f'FICTIONAL {t} {metric} annual {day}: {value} USD.',metric=metric,value=str(value),unit='USD',period=day,period_start=f'{year}-01-01',period_end=day,period_type='annual'))
        elif call.name in ('get_sec_filings','search_sec_filings'):
            text=RISKS[t]
            if call.name=='search_sec_filings' and t=='MSFT':text='Management attributes margin expansion to higher margin cloud services and expense discipline. This is fictional evidence.'
            records=[Evidence(id='passage:fixture:'+t+':'+call.name,source_id=source.id,ticker=t,text=text,section='risks',scope='unknown')]
        else:
            return ToolResult(status='no_data',limitations=['No frozen fixture for this tool.'])
        return ToolResult(status='ok' if records else 'no_data',evidence=records,sources=[source])

def snapshot(ticker,benchmark=False):
    if ticker not in ROWS and ticker!='SPY':raise ValueError('No frozen quote coverage')
    e=Evidence(id='price:fixture:'+ticker,source_id='price:fixture:'+ticker,ticker=ticker,text='FICTIONAL close: 100 USD.',metric='market_close',value='100',unit='USD')
    return {'symbol':ticker,'close':'100','currency':'USD','session':'2026-09-23','fresh':True,'moves':{},'evidence':e.model_dump(),'source':Source(id=e.source_id,title='FICTIONAL frozen quote',uri='https://example.invalid/quote',synthetic=True).model_dump()}

def guide(args):
    e=Evidence(id='guide:fixture:'+args.topic,source_id='guide:fixture:'+args.topic,ticker='GENERAL',text={'diversification':'Diversification spreads investments across different assets to reduce concentration risk. It does not guarantee protection from losses.', 'stocks':'A stock represents ownership in a company. Its value can fall, and dividends are not guaranteed.', 'bonds':'A bond is a loan to an issuer. Bonds carry credit risk and interest-rate risk; their prices can fall as interest rates rise.', 'funds':'A fund pools money to hold multiple investments. An ETF trades on an exchange. Funds can diversify holdings but still carry risk and fees.'}[args.topic])
    return ToolResult(status='ok',evidence=[e],sources=[Source(id=e.source_id,title='Evaluation education fixture',uri='https://example.invalid/guide',synthetic=True)])
