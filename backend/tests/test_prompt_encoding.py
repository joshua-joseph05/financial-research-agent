import json
from app.providers.prompt_encoding import compact_prompt as encode_prompt


def test_prompt_compaction_preserves_all_evidence_and_schema_values():
    payload={'question':'What changed—why?', 'observations':{'passage:1':{'text':'Issuer said: “not guaranteed”.\n  Keep exact quote spacing.','value':'12.00','input_ids':['a','b']}}, 'empty':None,'flag':False,'schema':{'type':'object','required':['evidence_ids']}}
    encoded=encode_prompt(payload)
    assert json.loads(encoded)==json.loads(json.dumps(payload))==payload
    assert len(encoded.encode())<len(json.dumps(payload).encode())
    assert json.loads(encoded)['observations']['passage:1']['text']==payload['observations']['passage:1']['text']


def test_both_providers_send_compact_prompts_with_unchanged_content(monkeypatch):
    import httpx
    from app.providers.llm import OllamaModel
    from app.providers.openrouter import OpenRouterModel
    from app.schemas import Plan
    monkeypatch.setattr("app.providers.llm.encode_prompt", encode_prompt)
    monkeypatch.setattr("app.providers.openrouter.encode_prompt", encode_prompt)
    captured=[]
    def handler(request):
        if request.url.path.endswith('/show'):
            return httpx.Response(200,json={})
        payload=json.loads(request.content)
        prompt=payload['messages'][1]['content']
        assert prompt==encode_prompt(json.loads(prompt))
        assert json.loads(prompt)['question']=='Explain “risk”.'
        captured.append(prompt)
        answer={'companies':[],'questions':['Explain risk']}
        if request.url.path.endswith('/chat'):
            return httpx.Response(200,json={'done':True,'message':{'content':json.dumps(answer)}})
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(answer)}}]})
    original=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(**kw,transport=httpx.MockTransport(handler)))
    monkeypatch.setenv('OPENROUTER_API_KEY','test-only')
    for model in [OllamaModel('gemma4:e4b'),OpenRouterModel()]:
        model.respond('plan',{'question':'Explain “risk”.'},Plan,10)
    assert len(captured)==2


def test_unvalidated_compaction_is_not_enabled_by_default():
    from app.providers.prompt_encoding import encode_prompt
    payload={'question':'What changed—why?', 'data':[1,2]}
    assert encode_prompt(payload)==json.dumps(payload)
