"""Verify the original company reference, not just an LLM's guessed ticker."""
import re
from app.ideas.models import IdeasClarification


def verify_references(selection, question, registry):
    references=getattr(selection,'company_references',[])
    if len(references)!=len(selection.tickers) or not references:
        raise IdeasClarification('Which stock ticker or full company name do you mean? I could not verify the company reference.')
    for reference,ticker in zip(references,selection.tickers):
        if not reference.strip() or not re.search(r'(?<!\w)'+re.escape(reference.strip())+r'(?!\w)',question,re.I):
            raise IdeasClarification('Which stock ticker or full company name do you mean? The company reference could not be matched to your question.')
        try:
            _,reference_cik,_=registry.sec.resolve(reference)
            _,ticker_cik,_=registry.sec.resolve(ticker)
        except (ValueError,AttributeError):
            raise IdeasClarification(f'Which stock ticker or full company name do you mean by "{reference}"? I could not resolve it uniquely.') from None
        except Exception:
            raise IdeasClarification('Issuer information is unavailable right now. Please retry, or confirm the full company name and stock ticker.') from None
        if reference_cik!=ticker_cik:
            raise IdeasClarification(f'Which stock ticker do you mean by "{reference}"? The proposed symbol did not match that company.')
