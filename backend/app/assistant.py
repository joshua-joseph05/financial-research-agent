"""One entry point, preserving the established research and investment graphs."""
import os
from typing import Literal
from pydantic import Field, field_validator
from app.schemas import Model
from app.ideas.models import IdeasRequest,IdeasClarification,EducationPlan
from app.ideas.graph import run_ideas,SYSTEM as IDEAS_SYSTEM
from app.agent.graph import run_research
from app.ideas.telemetry import MeteredModel
from app.providers.openrouter import create_model
from app.providers.llm import SYSTEM as RESEARCH_SYSTEM
from app.providers.sec import SECClient
from app.providers.demo import DemoModel
from app.tools.registry import ToolRegistry
from app.mcp.client import MCPToolRegistry

class AssistantRequest(Model):
    question:str=Field(min_length=3,max_length=2000)
    sentiment_enabled:bool=True
    mode:Literal['live','demo']='live'
    execution_profile:Literal['standard','efficient']='standard'
    @field_validator('question',mode='before')
    @classmethod
    def trim(cls,value):return value.strip() if isinstance(value,str) else value

class Route(Model):
    workflow:Literal['research','investment','education','clarification']
    reason:str=Field(max_length=200)
    clarification:str=Field(default='',max_length=300)


class EfficientRoute(Route):
    commentary_only: bool = Field(default=False, description='True only for named-company public opinions, analyst arguments or sentiment questions with NO request for financial fact checking, valuation, suitability, stock picks or a buying decision. Mixed requests must be false.')
    education_plan: EducationPlan | None = None
    unresolved_reference: str = Field(default='',max_length=200,
        description='Exact words in the question referring to missing prior conversation, an unnamed comparison target, or another unresolved entity. Empty only if the question is self-contained. Never infer past conversation.')


def run_assistant(payload,emit,model=None,registry=None):
    if payload.mode=='demo':
        with MCPToolRegistry(data='fixture') as demo_registry:
            report=run_research(payload.question,DemoModel(),registry=demo_registry,on_event=emit)['report']
        return {'workflow':'research','report':report,'routing':{'reason':'Explicit offline scripted demo; fictional data.'}}
    owned_sec=None
    try:
        if registry is None:
            registry=MCPToolRegistry();owned_sec=registry
        base=model or create_model(system_prompt=IDEAS_SYSTEM)
        meter=MeteredModel(base,36)
        emit({'phase':'route','event':'completed','result':{'message':'Understanding your question and choosing a research approach'}})
        routing_schema=EfficientRoute if payload.execution_profile=='efficient' else Route
        route=meter.respond('assistant_route',{'question':payload.question,'instruction':'Choose the best existing workflow for the actual intent, without answering the question. research: company facts, financial explanations, operating trends, business risks, or factual comparisons without a purchase decision. investment: purchase suitability/timing, investment candidates, stock discovery, investment comparisons, or competing market/sentiment arguments; includes mixed financial research and investment questions. education: general investing concepts without a company assessment. clarification: genuinely ambiguous, unrelated or unsupported requests; return a focused question. Do not ask for a ticker when a company name is supplied or for a sector when general discovery is requested. Do not force research questions into buying advice.' + (' For this profile, route explanatory company comparisons to research even when the user says long-term investments: business differences, financial strengths, and disclosed risks need sourced explanations, not purchase assessments. Use investment when the user asks which stock to choose/buy, whether or when to invest, asks for candidate discovery, or asks about public opinions, optimism, pessimism, expert agreement, analyst arguments or promised gains about a named company. These are company-specific sentiment investigations even without the words market or sentiment; do not route them to general education. Named-company due-diligence requests asking what to check or investigate before investing use investment: that workflow provides a beginner research checklist with company evidence. This is a request for research guidance, not a demand for a buy decision. General concept explanations without company-specific due diligence use education. Do not send a named-company checklist request into a sequence of generic investing guides or require personal circumstances merely to provide a research checklist. Merely mentioning investing does not require an investment recommendation. This request contains only the current question; there is no prior conversation to consult. Before choosing any workflow, check whether every specifically requested company can be identified. If a target is described only as the other company we discussed, that stock, or a similar missing-context reference, copy that exact phrase into unresolved_reference and ask which company it means. Do not fill it with a familiar peer. Broad discovery requests do not need named companies. For education only, return education_plan with topics and parts. Available guide topics: diversification (spreading holdings and concentration risk), stocks (ownership and dividends), bonds (lending, credit and interest-rate risks), funds (pooled investments, ETFs and fees). Choose topics matching the actual question. A question about whether a fund is diversified needs both funds and diversification guides; include requested definitions, concentration, fees and remaining loss risk in its parts. Write parts as specific, self-contained questions using the user wording, never a generic label such as definition. A simple question needs ONE part; a compound question needs only its distinct requested parts, at most four. Do not add unrequested topics or repeat parts. For other workflows or uncertain plans use education_plan=null. Set commentary_only=true only for investment questions asking solely about named-company commentary, opinions or expert agreement. Keep false for purchase decisions, financial corroboration, due-diligence checklists, discovery and mixed requests.' if payload.execution_profile=='efficient' else '')},routing_schema,60)
        if isinstance(route,EfficientRoute):
            import re
            reference=route.unresolved_reference.strip()
            # Some local models spell out an empty value. Never erase a literal
            # reference actually present in the user's question.
            present=bool(reference and re.search(re.escape(reference),payload.question,re.I))
            if reference.casefold() in {'n/a','none','null','empty','not applicable'} and not present:
                reference=''
            if reference:
                if not present:
                    raise IdeasClarification('Which company or comparison target do you mean? I could not match the requested reference reliably.')
                raise IdeasClarification(f'Which company or stock ticker do you mean by "{reference}"? This request does not include the earlier conversation.')
        if route.workflow=='clarification':raise IdeasClarification(route.clarification or 'What company or investing topic would you like to explore?')
        emit({'phase':'route','event':'completed','result':{'message':{'research':'Investigating company evidence','investment':'Investigating the investment question','education':'Explaining the investing concept'}[route.workflow]}})
        if route.workflow=='research':
            if hasattr(base,'system_prompt'):base.system_prompt=RESEARCH_SYSTEM
            report=run_research(payload.question,meter,registry=registry,on_event=emit,**({'execution_profile':'efficient'} if payload.execution_profile=='efficient' else {}))['report']
            report['telemetry']=meter.report()
        else:
            options={'execution_profile':'efficient'} if payload.execution_profile=='efficient' else {}
            if isinstance(route,EfficientRoute) and route.workflow=='investment' and route.commentary_only:
                options['commentary_only']=True
            if isinstance(route,EfficientRoute) and route.workflow=='education':
                if route.education_plan is None:
                    from app.ideas.education_planning import planning_context
                    route.education_plan=meter.respond('ideas_education_plan',planning_context(payload.question),EducationPlan,60)
                options['education_plan']=route.education_plan
            report=run_ideas(IdeasRequest(question=payload.question,sentiment_enabled=payload.sentiment_enabled),meter,registry,emit,**options)
        return {'workflow':route.workflow,'routing':{'reason':route.reason},'report':report}
    finally:
        if owned_sec:owned_sec.close()
