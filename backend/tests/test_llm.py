import json
from unittest.mock import patch

import httpx
import pytest

from app.providers.llm import OllamaModel
from app.schemas import Plan


def client_factory(handler):
    original = httpx.Client
    return lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler))


def test_local_adapter_sends_schema_and_parses_response():
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path == '/api/show':
            return httpx.Response(200, json={'details': {'format': 'gguf'}})
        return httpx.Response(200, json={'done': True, 'done_reason': 'stop', 'message': {
            'content': json.dumps({'companies': ['NVDA'], 'questions': ['Risks?']})}})
    with patch('app.providers.llm.httpx.Client', side_effect=client_factory(handler)):
        result = OllamaModel().respond('plan', {'question': 'Risks?'}, Plan, timeout=10)
    assert result.companies == ['NVDA']
    body = json.loads(requests[-1].content)
    assert body['format']['properties']['companies'] == Plan.model_json_schema()['properties']['companies']
    assert 'answer_type' in body['format']['required']
    assert 'evidence_requirements' in body['format']['required']
    assert body['format']['properties']['evidence_requirements']['minItems'] == 1
    assert body['stream'] is False
    assert body['options']['num_predict'] == 768
    assert all(r.url.host == '127.0.0.1' for r in requests)
    assert 'authorization' not in requests[-1].headers


def test_no_api_key_required(monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.delenv('OLLAMA_MODEL', raising=False)
    assert OllamaModel().model == 'gemma4:e4b'


@pytest.mark.parametrize('model', ['example:cloud', 'provider/model'])
def test_cloud_model_names_rejected(model):
    with pytest.raises(ValueError, match='local model'):
        OllamaModel(model)


def test_remote_metadata_prevents_generation():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'remote_host': 'https://ollama.com'})
    with patch('app.providers.llm.httpx.Client', side_effect=client_factory(handler)):
        with pytest.raises(ValueError, match='disabled'):
            OllamaModel().respond('plan', {}, Plan, timeout=10)
    assert len(requests) == 1


def test_truncated_response_is_rejected():
    def handler(request):
        return httpx.Response(200, json={} if request.url.path == '/api/show' else {
            'done': True, 'done_reason': 'length', 'message': {'content': '{}'}})
    with patch('app.providers.llm.httpx.Client', side_effect=client_factory(handler)):
        with pytest.raises(ValueError, match='incomplete'):
            OllamaModel().respond('plan', {}, Plan, timeout=10)


def test_generation_uses_typed_tools_and_observed_evidence_only():
    from app.providers.llm import response_schema
    from app.schemas import Decision, EvidenceReview, Verification, Synthesis
    from app.tools.registry import ToolRegistry
    action = response_schema('investigate', {'available_tools': ToolRegistry().descriptions()}, Decision)
    choices = action['$defs']['ToolCall']['anyOf']
    assert len(choices) == 5
    assert all(c['properties']['arguments']['additionalProperties'] is False for c in choices)
    assert action['properties']['findings']['maxItems'] == 0
    evidence = response_schema('assess', {'observations': {'source:1': {}}}, EvidenceReview)
    assert evidence['$defs']['Finding']['properties']['evidence_ids']['items']['enum'] == ['source:1']
    check = response_schema('verify', {'findings': [{'id':'claim:1'}]}, Verification)
    assert check['$defs']['ClaimCheck']['properties']['finding_id']['enum'] == ['claim:1']
    summary = response_schema('synthesize', {'findings': [{'id':'claim:1'}]}, Synthesis)
    assert summary['properties']['finding_ids']['items']['enum'] == ['claim:1']


def test_no_evidence_cannot_generate_citations():
    from app.providers.llm import response_schema
    from app.schemas import EvidenceReview, Verification, Synthesis
    assert response_schema('assess', {}, EvidenceReview)['properties']['findings']['maxItems'] == 0
    assert response_schema('verify', {}, Verification)['properties']['checks']['maxItems'] == 0
    assert response_schema('synthesize', {}, Synthesis)['properties']['finding_ids']['maxItems'] == 0


def test_schema_constraints_do_not_leak_between_runs():
    from app.providers.llm import response_schema
    from app.schemas import EvidenceReview
    response_schema('assess', {'observations':{'old:1':{}}}, EvidenceReview)
    second = response_schema('assess', {'observations':{'new:1':{}}}, EvidenceReview)
    assert second['$defs']['Finding']['properties']['evidence_ids']['items']['enum'] == ['new:1']
    assert 'enum' not in EvidenceReview.model_json_schema()['$defs']['Finding']['properties']['evidence_ids']['items']


def test_thinking_capable_local_model_uses_bounded_visible_output():
    requests=[]
    def handler(request):
        requests.append(request)
        if request.url.path == '/api/show':
            return httpx.Response(200, json={'capabilities':['completion','thinking']})
        return httpx.Response(200, json={'done':True,'done_reason':'stop','message':{
            'content':json.dumps({'companies':['NVDA'],'questions':['Risks?']})}})
    with patch('app.providers.llm.httpx.Client',side_effect=client_factory(handler)):
        OllamaModel('gemma4:e4b').respond('plan',{},Plan,timeout=10)
    assert json.loads(requests[-1].content)['think'] is False


def test_action_schema_couples_tool_choice_and_routing():
    from app.providers.llm import response_schema
    from app.schemas import Decision
    from app.tools.registry import ToolRegistry
    schema = response_schema('investigate', {'available_tools': ToolRegistry().descriptions()}, Decision)
    tool, verify = schema['anyOf']
    assert tool['properties']['action'] == {'const': 'tool'}
    assert tool['properties']['tool'] == {'$ref': '#/$defs/ToolCall'}
    assert verify['properties']['action'] == {'const': 'verify'}
    assert verify['properties']['tool'] == {'type': 'null'}
    assert all('reason' in branch['required'] for branch in schema['anyOf'])


def test_live_claim_schema_cannot_mix_scope_period_or_rewrite_calculation_ids():
    import re
    from app.providers.llm import response_schema
    from app.schemas import EvidenceReview
    observations = {
        'passage:current':{'ticker':'T','scope':'company','fiscal_years':[2026,2025]},
        'passage:segment':{'ticker':'T','scope':'segment','segment':'Consumer','fiscal_years':[2026,2025]},
        'passage:older':{'ticker':'T','scope':'company','fiscal_years':[2025,2024]},
    }
    schema=response_schema('assess',{'data_mode':'SEC filings','observations':observations,'research_periods':{'T':[2026,2025]}},EvidenceReview)
    props=schema['$defs']['Finding']['properties']
    assert not {'scope','segment','fiscal_years'} & props.keys()
    choices=props['evidence_ids']['anyOf']
    assert {tuple(choice['items']['enum']) for choice in choices} == {('passage:current',),('passage:segment',),('passage:older',)}
    assert not re.fullmatch(props['id']['pattern'],'derived:calc:one')
    assert re.fullmatch(props['id']['pattern'],'claim_driver')


def test_verification_schema_requires_each_noncanonical_claim_once():
    from app.providers.llm import response_schema
    from app.schemas import Verification
    schema=response_schema('verify',{'data_mode':'SEC filings','findings':[{'id':'derived:calc:one'},{'id':'claim_a'},{'id':'claim_b'}]},Verification)
    checks=schema['properties']['checks']
    assert checks['minItems']==checks['maxItems']==2
    assert [item['properties']['finding_id']['const'] for item in checks['prefixItems']]==['claim_a','claim_b']


def test_live_synthesis_cannot_generate_new_factual_prose():
    from app.providers.llm import response_schema
    from app.schemas import Synthesis
    schema=response_schema('synthesize',{'data_mode':'SEC filings','findings':[{'id':'claim_a'}]},Synthesis)
    assert schema['properties']['answer']=={'const':''}
    assert schema['properties']['unresolved_requirements']['maxItems']==3


def test_docker_host_ollama_endpoint(monkeypatch):
    monkeypatch.setenv('OLLAMA_BASE_URL', 'http://host.docker.internal:11434/')
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={} if request.url.path == '/api/show' else {
            'done': True, 'message': {'content': json.dumps({'companies': ['NVDA'], 'questions': ['Risks?']})}})
    with patch('app.providers.llm.httpx.Client', side_effect=client_factory(handler)):
        OllamaModel().respond('plan', {}, Plan, timeout=10)
    assert all(r.url.host == 'host.docker.internal' for r in requests)


@pytest.mark.parametrize('url', ['https://example.com', 'http://user:secret@localhost:11434', 'http://localhost:11434/proxy'])
def test_remote_ollama_endpoint_rejected(monkeypatch, url):
    monkeypatch.setenv('OLLAMA_BASE_URL', url)
    with pytest.raises(ValueError, match='local Ollama'):
        OllamaModel()
