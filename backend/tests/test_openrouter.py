import json
import httpx
import pytest
from app.providers.openrouter import OpenRouterModel,create_model,MODEL,ModelProviderError
from app.ideas.models import IdeasSelection


def mock_client(monkeypatch,handler):
    original=httpx.Client
    monkeypatch.setattr('app.providers.openrouter.httpx.Client',lambda **kwargs:original(**kwargs,transport=httpx.MockTransport(handler)))
    monkeypatch.setenv('OPENROUTER_API_KEY','test-secret')


def test_free_request_preserves_schema_and_selection_prompt(monkeypatch):
    def handler(request):
        data=json.loads(request.content)
        assert str(request.url)=='https://openrouter.ai/api/v1/chat/completions'
        assert request.headers['Authorization']=='Bearer test-secret'
        assert data['model']==MODEL
        assert 'models' not in data
        assert data['provider']['max_price']=={'prompt':0,'completion':0}
        assert data['provider']['require_parameters']
        assert data['response_format']['type']=='json_schema'
        assert 'resolve company names' in data['messages'][0]['content']
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"kind":"discovery","tickers":["MSFT"]}'}}]})
    mock_client(monkeypatch,handler)
    assert OpenRouterModel().respond('ideas_select',{},IdeasSelection,10).tickers==['MSFT']


@pytest.mark.parametrize('status',[401,402,429,404,500])
def test_provider_errors_are_safe_and_do_not_retry_paid(monkeypatch,status):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(status,json={'error':{'message':'test-secret private data'}})
    mock_client(monkeypatch,handler)
    with pytest.raises(ModelProviderError) as error:
        OpenRouterModel().respond('ideas_select',{},IdeasSelection,10)
    assert 'test-secret' not in str(error.value)
    assert len(calls)==1


@pytest.mark.parametrize('finish,content',[('length','{}'),('stop','not JSON'),('stop','{"kind":"unknown"}')])
def test_invalid_or_truncated_response_rejected(monkeypatch,finish,content):
    mock_client(monkeypatch,lambda request:httpx.Response(200,json={'choices':[{'finish_reason':finish,'message':{'content':content}}]}))
    with pytest.raises(ModelProviderError):OpenRouterModel().respond('ideas_select',{},IdeasSelection,10)


def test_configuration_and_paid_model_rejected(monkeypatch):
    monkeypatch.delenv('OPENROUTER_API_KEY',raising=False)
    monkeypatch.setenv('LLM_PROVIDER','openrouter')
    with pytest.raises(ModelProviderError,match='OPENROUTER_API_KEY'):create_model()
    monkeypatch.setenv('OPENROUTER_API_KEY','test-secret')
    assert isinstance(create_model(),OpenRouterModel)
    with pytest.raises(ModelProviderError,match='Only'):create_model('openai/gpt-oss-120b')
    monkeypatch.setenv('LLM_PROVIDER','unknown')
    with pytest.raises(ModelProviderError,match='LLM_PROVIDER'):create_model()


def test_embedded_overload_retried_once_then_clear_error(monkeypatch):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,json={'error':{'code':503,'message':'overloaded'}})
    mock_client(monkeypatch,handler)
    monkeypatch.setattr('app.providers.openrouter.time.sleep',lambda seconds:None)
    with pytest.raises(ModelProviderError,match='temporarily overloaded'):
        OpenRouterModel().respond('ideas_select',{},IdeasSelection,10)
    assert len(calls)==2
