"""Load and validate the versioned, manually authored benchmark labels."""
import json
from pathlib import Path
from typing import Literal
from pydantic import Field
from app.schemas import Model

CATEGORIES = ('financial_data', 'sec_filings', 'calculations', 'comparisons', 'open_research',
              'investment', 'sentiment_news', 'education', 'insufficient_evidence')

class Case(Model):
    id: str
    category: Literal['financial_data','sec_filings','calculations','comparisons','open_research',
                      'investment','sentiment_news','education','insufficient_evidence']
    question: str = Field(min_length=3, max_length=2000)
    expected_workflows: list[Literal['research','investment','education','clarification']]=Field(min_length=1)
    tickers: list[str]
    required_tool_groups: list[list[str]]
    allowed_tools: list[str]
    criteria: list[str] = Field(min_length=1)
    expected_outcome: Literal['answer','qualified_answer','clarification'] = 'answer'
    scenario: Literal['normal','unavailable_sources','missing_financials','ambiguous_company','no_recent_news','unsupported','stale_news','irrelevant_news'] = 'normal'
    sentiment_target: str | None = None


def load_cases(path=None):
    data=json.loads((Path(path) if path else Path(__file__).with_name('benchmark.json')).read_text())
    cases=[Case.model_validate(item) for item in data['cases']]
    if len({c.id for c in cases}) != len(cases):
        raise ValueError('Duplicate benchmark case IDs')
    return cases
