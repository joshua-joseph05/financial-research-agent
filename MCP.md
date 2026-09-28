# Financial tools over MCP

MCP is required for application financial-tool calls. The assistant, research and investment HTTP endpoints and research CLI launch a local stdio server automatically. There is no transport toggle and no direct API fallback. Python functions behind the server still call the same free public data sources and perform Decimal calculations. LangGraph remains responsible for planning, investigation, source verification and reporting.

## Install and run

From the project root, with the project's Python environment active:

```bash
python -m pip install -e './backend[dev]'
set -a
source .env
set +a
uvicorn app.api:app --host 127.0.0.1 --port 8000
```

MCP needs no API key, extra port, database or separately managed service. `SEC_USER_AGENT` still needs your application name and contact email. LLM configuration is unchanged. Restart the backend after installing. Docker users should rebuild with `docker compose up --build`; the server runs inside the existing backend container.

For another MCP client, configure a stdio server with your environment's absolute Python executable, arguments `-m app.mcp.server`, and `SEC_USER_AGENT` in its environment. Install the backend into that interpreter first. The `financial-mcp` console command is an equivalent server entry point. Do not run the server with an HTTP client: its stdout is reserved for MCP JSON-RPC messages.

## Tools and state

The server exposes the existing financial registry, including financials, history, filings, earnings, news, market data, company comparison, reconciliation and deterministic calculations. It additionally serves issuer resolution, market snapshots and scoped investment news search.

Each process serves one stdio client. Evidence is stored in memory for that session only, with a 2,000-record limit. First retrieve financial data, then pass its evidence IDs to `calculate_financial_metrics`. Chained calculations retain input IDs, values, units, periods and sources. Unknown IDs—including IDs from another session—fail. Clients cannot upload invented values as if the server retrieved them. Closing the run shuts down the client, child process and SEC client; no research findings are persisted by the server.

The MCP child receives SEC contact configuration, not LLM credentials. Tool failures return explicit errors; the agent cannot silently switch to direct financial API calls. A connection-startup failure fails the run.

Direct registries remain injectable for deterministic unit tests and frozen evaluations; this is not a production transport option. Financial arithmetic used to reproduce a result during verification remains a local validation check. Sentiment article discovery and reading remain specialist operations rather than financial MCP tools.

## Tests without external APIs or LLM calls

```bash
python -m pytest -q backend/tests/test_mcp.py
research 'Why did Microsoft margins change?' --mode demo --data fixture
```

The tests launch real subprocesses, perform MCP initialization and tool discovery, retrieve fixture financials, calculate from server-owned evidence and check that another session cannot reuse those IDs. They also check unsupported tools, no fallback, cleanup and the assistant's required MCP entry point. The explicit fixture mode uses fictional data solely for testing; live requests never automatically fall back to fixtures.

Built with the official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x), constrained to its supported 1.x interface (`mcp>=1.30,<2`).
