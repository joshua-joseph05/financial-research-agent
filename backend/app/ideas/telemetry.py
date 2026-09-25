"""Per-run counters; no prompts, credentials or private model reasoning logged."""
from contextvars import ContextVar
import time

ACTIVE=ContextVar('research_metrics',default=None)
class BudgetExceeded(ValueError):pass

class MeteredModel:
    def __init__(self,model,limit):
        self.model=model;self.limit=limit;self.used=0;self.calls=[];self.http_attempts=0;self.tokens={};self.started=time.monotonic()
    def reserve(self):
        if self.used>=self.limit:raise BudgetExceeded('Shared model request budget exhausted')
        self.used+=1
    def respond(self,phase,context,schema,timeout):
        self.reserve();start=time.monotonic();token=ACTIVE.set(self);status='ok'
        try:return self.model.respond(phase,context,schema,timeout)
        except Exception:
            status='error';raise
        finally:
            ACTIVE.reset(token)
            self.calls.append({'phase':phase,'role':context.get('specialist_role','lead'),'status':status,'seconds':round(time.monotonic()-start,3)})
    def report(self):
        return {'model_calls':len(self.calls),'request_budget_used':self.used,'request_budget':self.limit,'http_attempts':self.http_attempts,'tokens':self.tokens,'elapsed_seconds':round(time.monotonic()-self.started,3),'calls':self.calls}


def http_attempt(retry):
    meter=ACTIVE.get()
    if meter:
        if retry:meter.reserve()
        meter.http_attempts+=1


def record_usage(usage):
    meter=ACTIVE.get()
    if meter:
        for key in ('prompt_tokens','completion_tokens','total_tokens'):
            if isinstance(usage.get(key),int):meter.tokens[key]=meter.tokens.get(key,0)+usage[key]

class MeteredRegistry:
    def __init__(self,registry):self.registry=registry;self.calls=[]
    def __getattr__(self,name):return getattr(self.registry,name)
    def execute(self,call,observations):
        start=time.monotonic();status='error'
        try:
            result=self.registry.execute(call,observations);status=result.status;return result
        finally:self.calls.append({'name':call.name,'status':status,'seconds':round(time.monotonic()-start,3)})
