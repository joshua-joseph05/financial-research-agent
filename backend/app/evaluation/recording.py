"""Evaluation-only instrumentation around real workflows; no production graph edits."""
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import time
from unittest.mock import patch
from app import assistant
from app.agent.graph import run_research
from app.ideas.graph import run_ideas
from app.ideas.models import IdeasClarification
from app.ideas.sentiment import consult, ConsultArgs
from app.ideas.telemetry import MeteredModel
from app.providers.sec import SECClient
from app.tools.registry import ToolRegistry
from app.evaluation.sources import BenchmarkRegistry, source_environment
from app.evaluation.frozen_sources import AS_OF

class RecordingModel:
    def __init__(self,base,budget,progress=None,frozen=False):
        self.base=base
        self.frozen=frozen
        self.progress=progress or (lambda message:None)
        self.meter=MeteredModel(base,budget)
        self.decisions=[]
    @property
    def limit(self):return self.meter.limit
    @property
    def used(self):return self.meter.used
    @property
    def system_prompt(self):return getattr(self.base,'system_prompt','')
    @system_prompt.setter
    def system_prompt(self,value):self.base.system_prompt=value
    def respond(self,phase,context,schema,timeout):
        if self.frozen:
            context={**context,'evaluation_scope':'This is an offline exercise using fictional company records returned by replayed tools. Answer the question within that supplied dataset; do not present the figures as real company facts. The fictional label is a disclosure, not by itself an unanswered research requirement. Missing requested facts, ambiguous issuers, unsupported claims, and unavailable data remain genuine gaps. Do not use outside knowledge or invent missing records.'}
        item={'phase':phase,'status':'started','observation_ids':list(context.get('observations',{})),
              'available_tools':[s['name'] for s in context.get('available_tools',[])],
              'prior_tool_count':len(context.get('previous_calls',context.get('previous_tool_calls',[])))}
        self.decisions.append(item)
        self.progress(f"Model call {self.meter.used+1}: {phase} started")
        try:
            result=self.meter.respond(phase,context,schema,timeout)
            item.update(status='ok',output=result.model_dump())
            self.progress(f"Model call finished: {phase}")
            return result
        except Exception as error:
            item.update(status='error',error=type(error).__name__)
            self.progress(f"Model call failed: {phase} ({type(error).__name__})")
            raise

class RecordingRegistry:
    def __init__(self,base,started):self.base=base;self.calls=[];self.started=started
    def __getattr__(self,key):return getattr(self.base,key)
    def execute(self,call,observations):
        start=time.monotonic()
        item={'name':call.name,'arguments':deepcopy(call.arguments),'status':'error','at_seconds':round(start-self.started,4)}
        self.calls.append(item)
        try:
            result=self.base.execute(call,observations)
            item.update(status=result.status,result=result.model_dump())
            return result
        except Exception as error:
            item['error']=type(error).__name__;raise
        finally:item['seconds']=round(time.monotonic()-start,4)


def run_case(case,base_model,budget=36,mode='frozen',sentiment=True,target='assistant',registry=None,progress=None,execution_profile='standard'):
    """Sequential only: local patches are scoped to this dedicated evaluation process."""
    import os
    import app.ideas.tools as ideas_tools
    import app.ideas.sentiment as sentiment_module
    from app.ideas.market import snapshot
    from app.providers.investing_guides import investing_guide
    started=time.monotonic();model=RecordingModel(base_model,budget,progress,frozen=mode=='frozen')
    owned=None
    if registry is None:
        if mode=='frozen':registry=BenchmarkRegistry(case.scenario)
        else:
            owned=SECClient(os.getenv('SEC_USER_AGENT',''));registry=ToolRegistry(sec=owned)
    recorded=RecordingRegistry(registry,started)
    events=[];states={};articles={};extra_calls=[];specialists=[]
    result={'case_id':case.id,'category':case.category,'question':case.question,'target':target,
            'mode':mode,'sentiment_enabled':sentiment,'as_of':AS_OF if mode=='frozen' else datetime.now(timezone.utc).date().isoformat(),
            'status':'error','workflow':None,'report':None,'errors':[]}
    def record_service(name,fn,args):
        start=time.monotonic();item={'name':name,'arguments':args,'status':'error','at_seconds':round(start-started,4)};extra_calls.append(item)
        try:
            value=fn();item['status']='ok';item['result']=value.model_dump() if hasattr(value,'model_dump') else deepcopy(value)
            return value
        except Exception as error:item['error']=type(error).__name__;raise
        finally:item['seconds']=round(time.monotonic()-start,4)
    def shot(ticker,benchmark=False):
        fn=registry.snapshot if mode=='frozen' else snapshot
        return record_service('market_snapshot',lambda:fn(ticker,benchmark=benchmark),{'ticker':ticker,'benchmark':benchmark})
    def guide(args):
        fn=registry.guide if mode=='frozen' else investing_guide
        return record_service('get_investing_guide',lambda:fn(args),args.model_dump())
    reader=registry.read if mode=='frozen' else sentiment_module.sources.read
    def read(candidate,days,deadline):
        value=reader(candidate,days,deadline);articles[value['id']]=deepcopy(value);return value
    original_execute=ideas_tools.execute
    def execute(registry_arg,call,observations):
        if call.name=='search_web':return record_service('search_web',lambda:original_execute(registry_arg,call,observations),call.arguments)
        return original_execute(registry_arg,call,observations)
    def research(*args,**kwargs):
        state=run_research(*args,**kwargs);states['research']=state;return state
    def ideas(request,meter,registry_arg,emit,**options):
        return run_ideas(request,meter,registry_arg,emit,snapshot_fn=shot,guide_fn=guide,**options)
    def specialist(*args,**kwargs):
        value=consult(*args,**kwargs);specialists.append(value);return value
    try:
        with ExitStack() as stack:
            if mode=='frozen':stack.enter_context(source_environment(registry,read))
            else:stack.enter_context(patch('app.ideas.sentiment.sources.read',read))
            stack.enter_context(patch('app.assistant.run_research',research))
            stack.enter_context(patch('app.assistant.run_ideas',ideas))
            stack.enter_context(patch('app.ideas.tools.execute',execute))
            stack.enter_context(patch('app.ideas.sentiment.consult',specialist))
            if target=='sentiment':
                if not case.sentiment_target:raise ValueError('Case has no sentiment target')
                report=specialist(ConsultArgs(ticker=case.sentiment_target,objective=case.question[:300]),model,recorded,time.monotonic()+600,reserve=0,emit=events.append)
                result.update(workflow='sentiment',report=report,status='returned')
            else:
                envelope=assistant.run_assistant(assistant.AssistantRequest(question=case.question,sentiment_enabled=sentiment,execution_profile=execution_profile),events.append,model=model,registry=recorded)
                result.update(workflow=envelope['workflow'],report=envelope['report'],status='returned')
    except IdeasClarification as error:
        result.update(status='clarification',clarification=str(error))
    except Exception as error:
        result['errors'].append({'type':type(error).__name__})
    finally:
        if owned:owned.close()
    route=next((d['output']['workflow'] for d in model.decisions if d['phase']=='assistant_route' and d.get('output')),None)
    result['workflow']=result['workflow'] or route
    result['trace']={'model_decisions':model.decisions,'tool_calls':sorted(recorded.calls+extra_calls,key=lambda c:c['at_seconds']),'events':events,
                     'research_state':states.get('research'),'articles':articles,'sentiment_results':specialists}
    result['execution_profile']=execution_profile
    result['model']={'class':type(base_model).__name__,'name':getattr(base_model,'model',None)}
    result['telemetry']=model.meter.report()
    result['latency_seconds']=round(time.monotonic()-started,4)
    result['investigation_iterations']={
        'research':states.get('research',{}).get('iteration_count',sum(d['phase']=='investigate' for d in model.decisions)),
        'investment':sum(d['phase']=='ideas_investigate' for d in model.decisions),
        'sentiment':sum(c['phase']=='ideas_sentiment_step' for c in model.meter.calls),
    }
    return result
