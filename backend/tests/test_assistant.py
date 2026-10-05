import pytest
from fastapi.testclient import TestClient
from app import api
from app.assistant import AssistantRequest,Route,run_assistant
from app.ideas.models import IdeasClarification
from test_ideas import Registry

class Router:
    def __init__(self,workflow):self.workflow=workflow
    def respond(self,phase,context,schema,timeout):
        assert phase=='assistant_route'
        return Route(workflow=self.workflow,reason='Matches the question',clarification='Which company do you mean?')

@pytest.mark.parametrize('route',['research','investment','education'])
def test_unified_routes_preserve_question_and_existing_engines(monkeypatch,route):
    called=[]
    def research(question,model,registry,on_event):
        called.append(('research',question));return {'report':{'answer':'Reviewed research'}}
    def ideas(payload,model,registry,emit):
        called.append(('ideas',payload.question));assert payload.sentiment_enabled is False
        assert model.used==1
        return {'ideas':[]}
    monkeypatch.setattr('app.assistant.run_research',research);monkeypatch.setattr('app.assistant.run_ideas',ideas)
    result=run_assistant(AssistantRequest(question='Explain Microsoft margins',sentiment_enabled=False),lambda e:None,Router(route),Registry())
    assert result['workflow']==route
    assert called==[('research' if route=='research' else 'ideas','Explain Microsoft margins')]


def test_ambiguous_question_does_not_launch_research():
    with pytest.raises(IdeasClarification,match='Which company'):
        run_assistant(AssistantRequest(question='Which one?'),lambda e:None,Router('clarification'),Registry())


def test_unified_demo_works_without_network_or_model(monkeypatch):
    monkeypatch.delenv('SEC_USER_AGENT',raising=False)
    monkeypatch.setattr('app.assistant.create_model',lambda **k:pytest.fail('Demo must not call model'))
    with TestClient(api.app) as client:
        response=client.post('/assistant',json={'question':'Why have Microsoft operating margins changed?','mode':'demo'})
    assert response.status_code==200
    import json
    result=[json.loads(line) for line in response.text.splitlines() if json.loads(line)['type']=='report'][0]['report']
    assert result['workflow']=='research'
    assert result['report']['synthetic']


def test_unified_endpoint_uses_shared_busy_gate(monkeypatch):
    monkeypatch.setattr(api,'busy',True)
    with TestClient(api.app) as client:
        assert client.post('/assistant',json={'question':'What is diversification?'}).status_code==409


@pytest.mark.parametrize('workflow',['research','investment','education'])
def test_missing_context_is_checked_before_every_efficient_workflow(monkeypatch,workflow):
    from app.assistant import EfficientRoute
    class MissingContext:
        def respond(self,phase,context,schema,timeout):
            assert phase=='assistant_route'
            assert 'no prior conversation' in context['instruction']
            return EfficientRoute(workflow=workflow,reason='Comparison',unresolved_reference='that other company we discussed')
    monkeypatch.setattr('app.assistant.run_research',lambda *a,**k:pytest.fail('Must clarify before research'))
    monkeypatch.setattr('app.assistant.run_ideas',lambda *a,**k:pytest.fail('Must clarify before investment/education'))
    with pytest.raises(IdeasClarification,match='Which company or stock ticker'):
        run_assistant(AssistantRequest(question='Compare Apple with that other company we discussed.',execution_profile='efficient'),lambda e:None,MissingContext(),Registry())


def test_general_discovery_does_not_require_a_named_company(monkeypatch):
    from app.assistant import EfficientRoute
    class Discovery:
        def respond(self,phase,context,schema,timeout):
            return EfficientRoute(workflow='investment',reason='Discover research candidates',unresolved_reference='')
    monkeypatch.setattr('app.assistant.run_ideas',lambda *a,**k:{'ideas':[]})
    result=run_assistant(AssistantRequest(question='What stocks could I research?',execution_profile='efficient'),lambda e:None,Discovery(),Registry())
    assert result['workflow']=='investment'


@pytest.mark.parametrize('placeholder',['N/A','none','null','empty','not applicable'])
def test_empty_reference_placeholder_does_not_block_self_contained_request(monkeypatch,placeholder):
    from app.assistant import EfficientRoute
    class CompleteQuestion:
        def respond(self,phase,context,schema,timeout):
            return EfficientRoute(workflow='investment',reason='Sentiment',unresolved_reference=placeholder)
    monkeypatch.setattr('app.assistant.run_ideas',lambda *a,**k:{'ideas':[]})
    assert run_assistant(AssistantRequest(question='What are bullish and bearish arguments about Microsoft?',execution_profile='efficient'),lambda e:None,CompleteQuestion(),Registry())['workflow']=='investment'
    with pytest.raises(IdeasClarification,match='Which company or stock ticker'):
        run_assistant(AssistantRequest(question=f'Compare Microsoft with {placeholder}',execution_profile='efficient'),lambda e:None,CompleteQuestion(),Registry())
