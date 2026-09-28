"""Real stdio round trips: no model calls and no external financial API calls."""
import pytest
from app.mcp.client import MCPToolRegistry
from app.schemas import ToolCall
from app.tools.registry import ToolRegistry


def call(name,**args):return ToolCall(name=name,arguments=args)


def test_real_stdio_financials_and_chained_python_calculations():
    direct=ToolRegistry()
    with MCPToolRegistry(data='fixture') as remote:
        financials=remote.execute(call('get_financials',ticker='MSFT'),{})
        expected=direct.execute(call('get_financials',ticker='MSFT'),{})
        assert financials==expected and financials.status=='ok'
        rows={e.id:e.model_dump() for e in financials.evidence}
        income=next(e for e in financials.evidence if e.metric=='operating_income')
        revenue=next(e for e in financials.evidence if e.metric=='revenue' and e.period==income.period)
        calculation=call('calculate_financial_metrics',operation='operating_margin',evidence_ids=[income.id,revenue.id])
        result=remote.execute(calculation,{})  # Server owns evidence; no client data injection.
        assert result==direct.execute(calculation,rows)
        assert result.status=='ok' and result.evidence[0].input_ids==[income.id,revenue.id]
        assert result.sources and result.evidence[0].operation=='operating_margin'
    assert remote._future.done()
    remote.close()  # Idempotent cleanup.
    with MCPToolRegistry(data='fixture') as fresh:
        assert fresh.execute(calculation,rows).status=='error'  # No session leakage.


def test_unknown_tool_and_fabricated_inputs_fail_without_fallback(monkeypatch):
    with MCPToolRegistry(data='fixture') as remote:
        monkeypatch.setattr(ToolRegistry,'execute',lambda *a:pytest.fail('Direct execution in client'))
        assert remote.execute(call('invented_tool'),{}).status=='error'
        result=remote.execute(call('calculate_financial_metrics',operation='growth',evidence_ids=['fabricated:a','fabricated:b']),{})
        assert result.status=='error'
        assert {s['name'] for s in remote.descriptions()}=={'get_company_profile','get_financials','get_sec_filings','search_sec_filings','calculate_financial_metrics'}
    assert remote.execute(call('get_financials',ticker='MSFT'),{}).status=='error'


def test_missing_sec_identity_fails_before_start(monkeypatch):
    monkeypatch.delenv('SEC_USER_AGENT',raising=False)
    with pytest.raises(ValueError,match='SEC_USER_AGENT'):MCPToolRegistry()


def test_assistant_uses_mcp_for_default_registry(monkeypatch):
    from app import assistant
    class StopAfterRouting:
        def respond(self,*args,**kwargs):raise RuntimeError('stop')
    seen=[]
    class FakeRemote:
        def __init__(self):seen.append('opened')
        def close(self):seen.append('closed')
    monkeypatch.setattr(assistant,'MCPToolRegistry',FakeRemote)
    with pytest.raises(RuntimeError,match='stop'):
        assistant.run_assistant(assistant.AssistantRequest(question='Microsoft risks?'),lambda e:None,model=StopAfterRouting())
    assert seen==['opened','closed']
