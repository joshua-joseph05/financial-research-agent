"""Bounded, live-only research tools. No credentials beyond SEC contact identity."""
from typing import Literal
from types import SimpleNamespace
from pydantic import Field
from app.schemas import Model, ToolCall, ToolResult
from app.providers.sec import annual_facts
from app.providers.research_sources import earnings, news, market, reconcile

from app.providers.investing_guides import GuideArgs, investing_guide

Metric = Literal['revenue', 'operating_income', 'net_income', 'operating_cash_flow', 'capital_expenditure', 'operating_margin']


class HistoryArgs(Model):
    ticker: str = Field(min_length=1, max_length=20)
    metric: Metric = 'revenue'
    years: int = Field(default=5, ge=1, le=10)


class ComparisonArgs(Model):
    tickers: list[str] = Field(min_length=2, max_length=2)


class EarningsArgs(Model):
    ticker: str = Field(min_length=1, max_length=20)
    limit: int = Field(default=2, ge=1, le=3)


class NewsArgs(Model):
    ticker: str = Field(min_length=1, max_length=20)
    days: int = Field(default=30, ge=1, le=90)
    limit: int = Field(default=5, ge=1, le=8)


class MarketArgs(Model):
    ticker: str = Field(min_length=1, max_length=20)


class ReconcileArgs(Model):
    evidence_id: str = Field(min_length=1, max_length=200)


EXTRA_SPECS = {
    'get_investing_guide': (GuideArgs, 'Retrieve public Investor.gov educational material on diversification, stocks, bonds or funds. No ticker required. General concepts only, not current prices or personalized advice.'),
    'get_financial_metric_history': (HistoryArgs, 'Get 1–10 available annual SEC periods for one metric: revenue, operating_income, net_income, operating_cash_flow, capital_expenditure, operating_margin. Raw USD or Python-computed percent, exact dates, latest restatements. Missing years remain missing.'),
    'compare_companies': (ComparisonArgs, 'Retrieve latest two annual revenue/income windows for two companies and calculate each operating margin in Python. Returns source inputs and warns about different fiscal dates; no forced alignment or investment ranking.'),
    'get_earnings_information': (EarningsArgs, 'Read recent SEC 8-K Item 2.02 results announcements and up to two attached earnings-release exhibits per filing. Bounded excerpts; guidance is not a reported result. No earnings-call transcripts.'),
    'get_news': (NewsArgs, 'Find dated Google News RSS headlines about a resolved issuer. Discovery leads only: articles are not fetched or verified. Cite as reported headlines, never as established facts.'),
    'get_market_data': (MarketArgs, 'Get the latest available daily close, currency, exchange timezone and session timestamp from Yahoo public chart data. Best-effort unofficial endpoint, potentially delayed/incomplete. No real-time guarantee, market cap or valuation ratios.'),
    'reconcile_financial_figures': (ReconcileArgs, 'Cross-check one observed SEC annual USD fact against visible inline XBRL in the original filing table, with exact concept, dates, unit, scope and scale. Returns matched, mismatch or unresolved; never silently certifies unsupported layouts.'),
}


def execute_extended(registry, name, args, observations):
    sec = registry.sec
    if name == 'get_investing_guide':return investing_guide(args)
    if name == 'get_financial_metric_history':
        ticker, cik, _ = sec.resolve(args.ticker)
        metrics = ['revenue', 'operating_income'] if args.metric == 'operating_margin' else [args.metric]
        result = annual_facts(sec.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json'), ticker, cik, args.years, metrics)
        periods = sorted({e.period_end for e in result.evidence})
        if args.metric == 'operating_margin':
            local = {e.id: e.model_dump() for e in result.evidence}
            for end in periods:
                pair = {e.metric: e.id for e in result.evidence if e.period_end == end}
                computed = registry.execute(ToolCall(name='calculate_financial_metrics', arguments={'operation': 'operating_margin', 'evidence_ids': [pair['operating_income'], pair['revenue']]}), local)
                result.evidence.extend(computed.evidence)
                result.sources.extend(computed.sources)
                result.limitations.extend(computed.limitations)
        if len(periods) < args.years:
            result.limitations.append(f'Only {len(periods)} of {args.years} requested annual periods available for this standard tag; no interpolation.')
        return result
    if name == 'compare_companies':
        tickers = list(dict.fromkeys(sec.resolve(t)[0] for t in args.tickers))
        if len(tickers) < 2:
            raise ValueError('Comparison requires at least two different issuers')
        records, sources, limitations = [], {}, []
        ends = {}
        for ticker in tickers:
            result = sec.execute('get_financials', SimpleNamespace(ticker=ticker))
            records.extend(result.evidence)
            sources.update({s.id: s for s in result.sources})
            limitations.extend(result.limitations)
            if not result.evidence:
                limitations.append(f'{ticker}: comparable annual financials unavailable')
                continue
            local = {e.id: e.model_dump() for e in records}
            ends[ticker] = sorted({e.period_end for e in result.evidence})
            for end in ends[ticker]:
                pair = {e.metric: e.id for e in result.evidence if e.period_end == end}
                calc = registry.execute(ToolCall(name='calculate_financial_metrics', arguments={'operation': 'operating_margin', 'evidence_ids': [pair['operating_income'], pair['revenue']]}), local)
                if calc.status != 'ok':
                    limitations.extend(calc.limitations)
                    continue
                records.extend(calc.evidence)
                sources.update({s.id: s for s in calc.sources})
        if len({tuple(dates) for dates in ends.values()}) > 1:
            limitations.append('Fiscal windows differ across issuers. These are each company’s reported annual periods, not aligned calendar periods; do not directly attribute differences to operating performance alone.')
        limitations.append('Comparison covers annual revenue, operating income and margins only. Business mix and accounting differences require filing research; no buy/sell ranking.')
        return ToolResult(status='ok' if records else 'no_data', evidence=records, sources=list(sources.values()), limitations=list(dict.fromkeys(limitations)))
    if name == 'get_earnings_information':
        return earnings(sec, args)
    if name == 'get_news':
        return news(sec, args)
    if name == 'get_market_data':
        return market(sec, args)
    if name == 'reconcile_financial_figures':
        return reconcile(sec, args, observations)
    raise ValueError('Unknown extended tool')
