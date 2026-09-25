"""One entry point, preserving the established research and investment graphs."""
import os
from typing import Literal
from pydantic import Field, field_validator
from app.schemas import Model
from app.ideas.models import IdeasRequest,IdeasClarification
from app.ideas.graph import run_ideas,SYSTEM as IDEAS_SYSTEM
from app.agent.graph import run_research
from app.ideas.telemetry import MeteredModel
from app.providers.openrouter import create_model
from app.providers.llm import SYSTEM as RESEARCH_SYSTEM
from app.providers.sec import SECClient
from app.providers.demo import DemoModel
from app.tools.registry import ToolRegistry

class AssistantRequest(Model):
    question:str=Field(min_length=3,max_length=2000)
    sentiment_enabled:bool=True
    mode:Literal['live','demo']='live'
    @field_validator('question',mode='before')
    @classmethod
    def trim(cls,value):return value.strip() if isinstance(value,str) else value

class Route(Model):
    workflow:Literal['research','investment','education','clarification']
    reason:str=Field(max_length=200)
    clarification:str=Field(default='',max_length=300)


def run_assistant(payload,emit,model=None,registry=None):
    if payload.mode=='demo':
        report=run_research(payload.question,DemoModel(),registry=ToolRegistry(),on_event=emit)['report']
        return {'workflow':'research','report':report,'routing':{'reason':'Explicit offline scripted demo; fictional data.'}}
    owned_sec=None
    try:
        if registry is None:
            owned_sec=SECClient(os.getenv('SEC_USER_AGENT',''));registry=ToolRegistry(sec=owned_sec)
        base=model or create_model(system_prompt=IDEAS_SYSTEM)
        meter=MeteredModel(base,36)
        emit({'phase':'route','event':'completed','result':{'message':'Understanding your question and choosing a research approach'}})
        route=meter.respond('assistant_route',{'question':payload.question,'instruction':'Choose the best existing workflow for the actual intent, without answering the question. research: company facts, financial explanations, operating trends, business risks, or factual comparisons without a purchase decision. investment: purchase suitability/timing, investment candidates, stock discovery, investment comparisons, or competing market/sentiment arguments; includes mixed financial research and investment questions. education: general investing concepts without a company assessment. clarification: genuinely ambiguous, unrelated or unsupported requests; return a focused question. Do not ask for a ticker when a company name is supplied or for a sector when general discovery is requested. Do not force research questions into buying advice.'},Route,60)
        if route.workflow=='clarification':raise IdeasClarification(route.clarification or 'What company or investing topic would you like to explore?')
        emit({'phase':'route','event':'completed','result':{'message':{'research':'Investigating company evidence','investment':'Investigating the investment question','education':'Explaining the investing concept'}[route.workflow]}})
        if route.workflow=='research':
            if hasattr(base,'system_prompt'):base.system_prompt=RESEARCH_SYSTEM
            report=run_research(payload.question,meter,registry=registry,on_event=emit)['report']
            report['telemetry']=meter.report()
        else:
            report=run_ideas(IdeasRequest(question=payload.question,sentiment_enabled=payload.sentiment_enabled),meter,registry,emit)
        return {'workflow':route.workflow,'routing':{'reason':route.reason},'report':report}
    finally:
        if owned_sec:owned_sec.close()
