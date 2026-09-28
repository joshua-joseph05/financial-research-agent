"""Investment-only tool additions; all calculations use the shared Python registry."""
from pydantic import Field
from app.schemas import Model, ToolResult
from app.providers.research_sources import news


class WebSearchArgs(Model):
    ticker: str = Field(min_length=1,max_length=20)
    query: str = Field(min_length=1,max_length=160)
    days: int = Field(default=30,ge=1,le=90)
    limit: int = Field(default=4,ge=1,le=6)


def descriptions(registry):
    return registry.descriptions()+[{'name':'search_web','description':'Free company-scoped web NEWS search via Google News RSS. Query a topic such as export restrictions. Returns unverified headlines and links only, not article bodies. Investigate leads using filings or earnings tools before making claims.','input_schema':WebSearchArgs.model_json_schema()}]


def execute(registry,call,observations):
    if call.name!='search_web' or getattr(registry,'transport',None)=='mcp':return registry.execute(call,observations)
    args=WebSearchArgs.model_validate(call.arguments)
    if not getattr(registry,'sec',None):return ToolResult(status='no_data',limitations=['Web news search requires a configured SEC issuer resolver.'])
    return news(registry.sec,args)
