from typing import Literal
from pydantic import Field, field_validator, model_validator
from app.schemas import Model


class IdeasRequest(Model):
    question: str = Field(default='Which of these stocks should I consider buying, and how should I approach timing?', min_length=3, max_length=2500)
    tickers: list[str] = Field(default_factory=list,min_length=0,max_length=4)
    sentiment_enabled: bool = True
    max_model_requests: int = Field(default=36,ge=4,le=48)
    research_size: int = Field(default=8,ge=3,le=25)
    mode: Literal['question','compare'] = 'question'
    horizon: Literal['under_3_years','3_to_5_years','5_plus_years','custom','unspecified'] = 'unspecified'
    horizon_text: str = Field(default='', max_length=160)
    risk_tolerance: Literal['low','medium','high','unspecified'] = 'unspecified'

    @model_validator(mode='after')
    def resolve_custom_horizon(self):
        if self.horizon == 'custom':
            from app.ideas.horizon import interpret_horizon
            self.horizon_text = self.horizon_text.strip()
            if not self.horizon_text:
                raise ValueError('Describe when you might need the money')
            self.horizon = interpret_horizon(self.horizon_text)
        else:
            self.horizon_text = ''
        return self

    @field_validator('question')
    @classmethod
    def trim_question(cls,value):
        if len(value.strip())<3: raise ValueError('Enter a question')
        return value.strip()

    @field_validator('tickers')
    @classmethod
    def clean_tickers(cls,values):
        import re
        result=list(dict.fromkeys(v.strip().upper() for v in values))
        if any(not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,9}',v) for v in result):
            raise ValueError('Use US stock ticker symbols, for example MSFT')
        return result


class IdeasPlan(Model):
    focus: Literal['long_term_comparison','single_company_research'] = 'long_term_comparison'
    checks: list[Literal['financial_performance','disclosed_risks','dated_prices','market_context','valuation_gaps']] = Field(min_length=1,max_length=5)


class Rationale(Model):
    text: str = Field(max_length=450)
    evidence_ids: list[str] = Field(min_length=1,max_length=3)


class StockIdea(Model):
    ticker: str
    action: Literal['consider_gradual_buying','watch','avoid_for_now']
    reasons: list[Rationale] = Field(min_length=1,max_length=2)
    risks: list[Rationale] = Field(min_length=1,max_length=2)


class IdeasDraft(Model):
    answer_intent: Literal['information','investment_decision'] = Field(default='investment_decision', description='Use information for explanations, analyst commentary, factual comparisons, and research checklists. Use investment_decision only when the question asks whether/what to buy, sell, hold, or when to invest. Classify the user question, not the tools used.')
    ideas: list[StockIdea] = Field(max_length=25)


class IdeaCheck(Model):
    ticker: str
    supported: bool
    explanation: str = Field(max_length=350)


class IdeasReview(Model):
    checks: list[IdeaCheck] = Field(max_length=25)


class IdeasSelection(Model):
    kind: Literal['named_companies','discovery','education','clarification']
    topics: list[Literal['diversification','stocks','bonds','funds']] = Field(default_factory=list,max_length=3)
    user_horizon_text: str = Field(default='',max_length=160)
    user_risk_tolerance: Literal['low','medium','high','unspecified'] = 'unspecified'
    tickers: list[str] = Field(default_factory=list,max_length=25)
    clarification: str = Field(default='',max_length=300)

    @field_validator('tickers')
    @classmethod
    def clean_tickers(cls,values):
        return IdeasRequest.clean_tickers(values)


class ResolvedIdeasSelection(IdeasSelection):
    company_references: list[str] = Field(max_length=25, description='For named_companies, copy each company name or ticker EXACTLY from the user question, in the same order as tickers. For discovery, education, or clarification return an empty list.')


class IdeasClarification(ValueError):
    """A user-facing question that needs more detail."""


class IdeasInvestigation(Model):
    action: Literal['tool','finish']
    reason: str = Field(max_length=300)
    tool: dict | None = None

    @model_validator(mode='after')
    def tool_matches_action(self):
        if self.action=='tool' and self.tool is None:
            raise ValueError('A tool action requires a tool name and arguments')
        if self.action=='finish' and self.tool is not None:
            raise ValueError('A finish action cannot execute a tool')
        return self


class QuestionInvestigation(IdeasInvestigation):
    question_answered: bool = Field(description='Does existing evidence, reviewed sentiment and displayed checklist cover the original question? Optional background research is not a missing requirement. This is provisional; final source and question-coverage review still follows.')
    remaining_question: str = Field(max_length=300, description='Specific unanswered part of the user question requiring another tool, or empty when answered. A specialist verification task is required only when the user asks to establish that underlying claim or make an investment decision.')


class EducationalSection(Model):
    title: str = Field(max_length=100)
    text: str = Field(max_length=700)
    evidence_ids: list[str] = Field(min_length=1,max_length=4)

class EducationalAnswer(Model):
    sections: list[EducationalSection] = Field(min_length=1,max_length=5)
    remaining_questions: list[str] = Field(default_factory=list,max_length=3)

class EducationalReview(Model):
    supported: bool
    explanation: str = Field(max_length=300)



class EducationPlan(Model):
    topics: list[Literal['diversification','stocks','bonds','funds']] = Field(min_length=1,max_length=4)
    parts: list[str] = Field(min_length=1,max_length=4)


class EducationalPartCheck(Model):
    part_index: int = Field(ge=0,le=3)
    answer_section_index: int = Field(ge=0,le=4)


class EducationalCoverageReview(EducationalReview):
    original_question_covered: bool = Field(description='Does the answer cover the entire original user question, including any requested parts the plan omitted?')
    explanation: str = Field(max_length=160)
    covered_parts: list[EducationalPartCheck] = Field(max_length=4)
    missing_parts: list[int] = Field(max_length=4)
