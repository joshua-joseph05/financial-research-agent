"""One stdio client per process; evidence lives only for that connection."""
import argparse
import asyncio
import os
import anyio
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, ToolAnnotations
from pydantic import Field
from app.schemas import Model, ToolCall, ToolResult
from app.tools.registry import ToolRegistry
from app.providers.sec import SECClient
from app.ideas.market import snapshot
from app.ideas.tools import WebSearchArgs
from app.providers.research_sources import news


class SnapshotArgs(Model):
    ticker: str = Field(min_length=1, max_length=20, pattern=r'^[A-Za-z0-9.\-]+$')
    benchmark: bool = False


class ResolveArgs(Model):
    company: str = Field(min_length=1, max_length=100)


def create_server(registry):
    server=Server('financial-research-tools')
    observations={}
    lock=asyncio.Lock()
    specs={s['name']:s for s in registry.descriptions()}
    if registry.sec:specs['search_web']={'name':'search_web','description':'Company-scoped news search. Unverified headlines and links, not verified article evidence.','input_schema':WebSearchArgs.model_json_schema()}

    @server.list_tools()
    async def list_tools():
        result=[Tool(name=s['name'],description=s['description'],inputSchema=s['input_schema'],outputSchema=ToolResult.model_json_schema(),annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False)) for s in specs.values()]
        if registry.sec:
            result += [Tool(name='resolve_issuer',description='Resolve a company name or ticker to SEC identity.',inputSchema=ResolveArgs.model_json_schema()),Tool(name='get_market_snapshot',description='Dated market snapshot including recent price changes; not live pricing.',inputSchema=SnapshotArgs.model_json_schema())]
        return result

    @server.call_tool()
    async def call_tool(name, arguments):
        async with lock:
            if name=='resolve_issuer' and registry.sec:
                args=ResolveArgs.model_validate(arguments)
                ticker,cik,company=await anyio.to_thread.run_sync(registry.sec.resolve,args.company)
                return {'ticker':ticker,'cik':cik,'company':company}
            if name=='get_market_snapshot' and registry.sec:
                args=SnapshotArgs.model_validate(arguments)
                result=await anyio.to_thread.run_sync(lambda:snapshot(args.ticker,benchmark=args.benchmark))
                if len(observations)>=2000:raise ValueError('Session evidence limit reached')
                observations[result['evidence']['id']]=result['evidence']
                return result
            if name not in specs:raise ValueError('Unknown financial tool')
            call=registry.normalize_call(ToolCall(name=name,arguments=arguments))
            if name=='search_web':
                args=WebSearchArgs.model_validate(arguments)
                result=await anyio.to_thread.run_sync(news,registry.sec,args)
            else:
                result=await anyio.to_thread.run_sync(registry.execute,call,observations)
            incoming={e.id:e.model_dump() for e in result.evidence}
            if len(observations.keys() | incoming.keys())>2000:
                return ToolResult(status='error',limitations=['Session evidence limit reached; start a new research run.']).model_dump()
            observations.update(incoming)
            return result.model_dump()

    return server


async def serve(data):
    sec=SECClient(os.getenv('SEC_USER_AGENT','')) if data=='sec' else None
    try:
        server=create_server(ToolRegistry(sec=sec))
        async with stdio_server() as (read,write):
            await server.run(read,write,server.create_initialization_options())
    finally:
        if sec:sec.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',choices=['sec','fixture'],default='sec')
    args=parser.parse_args()
    asyncio.run(serve(args.data))

if __name__=='__main__':main()
