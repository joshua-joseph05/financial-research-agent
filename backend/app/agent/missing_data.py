"""Explain failed financial retrieval without inventing a company fact."""
import re

FINANCIAL_TOOLS={'get_financials','get_financial_metric_history','compare_companies'}


def missing_financial_explanation(state):
    observations=state.get('observations',{}).values()
    if any(e.get('value') is not None and not e.get('operation') and e.get('metric')!='market_close' for e in observations):
        return None
    failed=[c for c in state.get('tool_calls',[]) if c.get('name') in FINANCIAL_TOOLS and c.get('result',{}).get('status') in ('no_data','error')]
    if not failed:return None
    text='This run could not retrieve the requested financial figures. This does not establish that the company has not published them. '
    question=state['question'].casefold()
    if re.search(r'\boperating\s+margin\b',question):
        text+='Operating margin needs operating income and revenue for the same reporting period and currency. The calculation is operating income divided by revenue, multiplied by 100 to express it as a percentage. Revenue must be positive. '
        if re.search(r'\b(change|changed|changes|difference|compare|between)\b',question):
            text+='To compare periods, calculate each margin separately and subtract the earlier margin from the later one; that difference is in percentage points. '
    elif re.search(r'\b(growth|grew|percentage (?:change|increase|decrease))\b',question):
        text+='Percentage growth needs the earlier and later values of the same metric, with comparable periods, scope and currency. Subtract the earlier value from the later one, divide by the earlier value, then multiply by 100. This tool requires a positive earlier value. '
    else:
        text+='The requested reported values, dates and units are needed before a supported numerical answer can be given. '
    return text+'No result was calculated. Missing figures were not treated as zero, and forecasts or a different period were not substituted. Retry the source or supply the reported figures for the requested period.'
