"""Synchronous LangGraph tool adapter using an actual stdio MCP subprocess."""
from concurrent.futures import Future
from datetime import timedelta
from pathlib import Path
import os
import sys
import anyio
from anyio.from_thread import start_blocking_portal
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from app.schemas import ToolCall, ToolResult
from app.tools.registry import ToolRegistry


class RemoteSEC:
    def __init__(self,owner):self.owner=owner
    def resolve(self,company):
        row=self.owner._call('resolve_issuer',{'company':company})
        return row['ticker'],row['cik'],row['company']


class MCPToolRegistry(ToolRegistry):
    transport = "mcp"
    def __init__(self,data='sec'):
        if data not in ('sec','fixture'):raise ValueError('Unknown MCP data mode')
        if data=='sec' and not os.getenv('SEC_USER_AGENT'):raise ValueError('SEC_USER_AGENT is required')
        self._closed=False
        self._ready=Future()
        self._stop=None
        self._portal_cm=start_blocking_portal()
        self._portal=self._portal_cm.__enter__()
        self._future=self._portal.start_task_soon(self._connect,data)
        try:
            self._remote_specs=self._ready.result(timeout=30)
            super().__init__(sec=RemoteSEC(self) if data=='sec' else None)
        except BaseException:
            self.close()
            raise

    async def _connect(self,data):
        # Only provider identity is passed; the child does not receive LLM keys.
        env={'SEC_USER_AGENT':os.getenv('SEC_USER_AGENT',''),'PYTHONUNBUFFERED':'1',
             'PYTHONPATH':str(Path(__file__).resolve().parents[2])}
        params=StdioServerParameters(command=sys.executable,args=['-m','app.mcp.server','--data',data],env=env)
        try:
            async with stdio_client(params) as (read,write):
                async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=120)) as session:
                    self._session=session
                    await session.initialize()
                    tools=await session.list_tools()
                    self._stop=anyio.Event()
                    self._ready.set_result({t.name:t for t in tools.tools})
                    await self._stop.wait()
        except BaseException as error:
            if not self._ready.done():self._ready.set_exception(error)
            else:raise

    def _call(self,name,arguments):
        if self._closed:raise RuntimeError('MCP session is closed')
        result=self._portal.call(self._session.call_tool,name,arguments)
        if result.isError:raise ValueError('MCP financial tool failed: '+name)
        if not isinstance(result.structuredContent,dict):raise ValueError('MCP returned no structured result')
        return result.structuredContent

    def descriptions(self,observations=None,previous_calls=None):
        # Reuse Python operand constraints; tool availability comes from MCP.
        result=super().descriptions(observations,previous_calls)
        return [{**s,'description':self._remote_specs[s['name']].description} for s in result if s['name'] in self._remote_specs]

    def execute(self,call,observations):
        # Never accept arbitrary client-supplied numbers as server-owned evidence.
        call=self.normalize_call(call)
        try:return ToolResult.model_validate(self._call(call.name,call.arguments))
        except Exception as error:
            return ToolResult(status='error',limitations=[f'MCP tool unavailable ({type(error).__name__}); no direct fallback was used.'])

    def snapshot(self,ticker,benchmark=False):
        return self._call('get_market_snapshot',{'ticker':ticker,'benchmark':benchmark})

    def close(self):
        if self._closed:return
        self._closed=True
        try:
            if self._stop is not None:self._portal.call(self._stop.set)
            else:self._future.cancel()
            self._future.result(timeout=15)
        finally:self._portal_cm.__exit__(None,None,None)

    def __enter__(self):return self
    def __exit__(self,*exc):self.close()
