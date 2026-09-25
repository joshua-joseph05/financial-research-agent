"""Hosted inference restricted to the explicitly free Nemotron endpoint."""
import json
import os
import time
import httpx
from app.providers.llm import SYSTEM, phase_prompt, response_schema

MODEL = 'nvidia/nemotron-3-super-120b-a12b:free'


class ModelProviderError(ValueError):
    """Safe user-facing provider error, without request or credential contents."""


class OpenRouterModel:
    def __init__(self, model=None, system_prompt=None):
        if model and model != MODEL:
            raise ModelProviderError('Only nvidia/nemotron-3-super-120b-a12b:free is enabled for OpenRouter.')
        self.model=MODEL
        self.system_prompt=system_prompt or SYSTEM
        self.api_key=os.getenv('OPENROUTER_API_KEY','').strip()
        if not self.api_key:
            raise ModelProviderError('Set OPENROUTER_API_KEY in the backend .env and restart the backend.')

    def respond(self, phase, context, schema, timeout):
        payload={
            'model':MODEL, 'stream':False, 'temperature':0, 'max_tokens':8192,
            'provider':{'require_parameters':True,'max_price':{'prompt':0,'completion':0}},
            'response_format':{'type':'json_schema','json_schema':{
                'name':schema.__name__,'strict':False,'schema':response_schema(phase,context,schema)}},
            'messages':[
                {'role':'system','content':phase_prompt(phase,self.system_prompt)},
                {'role':'user','content':json.dumps({'phase':phase,**context,'output_instruction':'Return only JSON matching output_schema. Include all schema properties needed for the task, even when optional.', 'output_schema':response_schema(phase,context,schema)})},
            ],
        }
        try:
            with httpx.Client(base_url='https://openrouter.ai/api/v1/',trust_env=False,follow_redirects=False,timeout=timeout) as client:
                deadline=time.monotonic()+timeout
                for attempt in range(2):
                    remaining=deadline-time.monotonic()
                    if remaining<=0:raise httpx.ReadTimeout('Request budget exhausted')
                    from app.ideas.telemetry import http_attempt
                    http_attempt(attempt>0)
                    response=client.post('chat/completions',headers={'Authorization':'Bearer '+self.api_key},json=payload,timeout=remaining)
                    try: embedded_error=response.json().get('error',{})
                    except (ValueError,AttributeError): embedded_error={}
                    overloaded=response.status_code==503 or embedded_error.get('code')==503
                    if not overloaded:break
                    if attempt==1 or deadline-time.monotonic()<2:
                        raise ModelProviderError('The free model provider is temporarily overloaded. Please retry shortly; no paid fallback was used.')
                    time.sleep(1)
        except httpx.TimeoutException:
            raise ModelProviderError('OpenRouter timed out. Retry with fewer stocks.') from None
        except httpx.RequestError:
            raise ModelProviderError('Could not connect to OpenRouter. Check the network and retry.') from None
        if response.status_code!=200:
            messages={401:'OpenRouter rejected the API key. Check OPENROUTER_API_KEY.',402:'OpenRouter rejected this free request. No paid fallback was attempted.',429:'OpenRouter free-tier limit reached. Wait for your quota to reset, or switch to Ollama.',404:'The free model has no compatible endpoint available. Retry later or use Ollama.',400:'OpenRouter rejected the structured request. The free endpoint may not support the required schema.'}
            raise ModelProviderError(messages.get(response.status_code,'OpenRouter is unavailable. No paid fallback was attempted.'))
        try:
            result=response.json()
            from app.ideas.telemetry import record_usage
            record_usage(result.get('usage') or {})
            choice=result['choices'][0]
            if choice.get('finish_reason')!='stop' or choice['message'].get('refusal'):
                raise ValueError('Incomplete response')
            return schema.model_validate_json(choice['message']['content'])
        except (ValueError,KeyError,IndexError,TypeError):
            raise ModelProviderError('OpenRouter returned an incomplete or invalid structured response.') from None


def create_model(model=None, system_prompt=None):
    from app.providers.llm import OllamaModel
    provider=os.getenv('LLM_PROVIDER','ollama').strip().lower()
    if provider=='openrouter':return OpenRouterModel(model,system_prompt)
    if provider=='ollama':return OllamaModel(model,system_prompt)
    raise ModelProviderError('LLM_PROVIDER must be ollama or openrouter.')
