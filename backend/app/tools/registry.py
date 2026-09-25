import hashlib
import json
import re
import httpx
from importlib.resources import files
from typing import Literal

from pydantic import Field, ValidationError

from app.schemas import Evidence, Model, Source, ToolCall, ToolResult
from app.tools.calculations import calculate
from app.tools.extended import EXTRA_SPECS, execute_extended


class CompanyArgs(Model):
    ticker: str = Field(min_length=1, max_length=20)


class FilingArgs(CompanyArgs):
    scope: Literal["company", "segment", "all"] = "all"
    fiscal_year: int | None = Field(default=None, ge=1990, le=2100)
    section: str | None = Field(default=None, max_length=80)


class SearchArgs(CompanyArgs):
    scope: Literal["company", "segment", "all"] = "all"
    fiscal_year: int | None = Field(default=None, ge=1990, le=2100)
    query: str = Field(min_length=1, max_length=200)


class CalculationArgs(Model):
    operation: Literal["operating_margin", "growth", "margin_change", "compare_operating_margins"]
    evidence_ids: list[str] = Field(min_length=2, max_length=4)


SPECS = {
    "get_company_profile": (CompanyArgs, "Resolve NVDA, MSFT, AMD, AAPL or their company names. Synthetic identity data."),
    "get_financials": (CompanyArgs, "Get synthetic 2024 and 2025 annual revenue and operating income, USD millions."),
    "get_sec_filings": (FilingArgs, "Read synthetic filing sections. Omit section to read all; section names include business, risks, md&a."),
    "search_sec_filings": (SearchArgs, "Keyword search synthetic filing passages. Any query word can match; no semantic search."),
    "calculate_financial_metrics": (CalculationArgs, "Deterministic calculation on observed evidence IDs. For margin trends choose compare_operating_margins: newest income/revenue then prior income/revenue (four IDs); returns both margins and percentage-point change. Single margin: income then revenue. Growth/change: newest then oldest."),
}


SPECS.update(EXTRA_SPECS)

class ToolRegistry:
    def __init__(self, sec=None):
        self.sec = sec
        self.synthetic = sec is None
        self.data = json.loads(files("app").joinpath("fixtures/companies.json").read_text())

    def descriptions(self, observations=None, previous_calls=None) -> list[dict]:
        specs = [{"name": name, "description": desc, "input_schema": schema.model_json_schema()}
                 for name, (schema, desc) in SPECS.items() if self.sec or name not in EXTRA_SPECS]
        if self.sec:
            descriptions = {
                "get_company_profile": "Resolve exact SEC ticker and retrieve SEC issuer identity.",
                "get_financials": "Get latest two shared annual revenue and operating-income fiscal windows, raw USD, with filing provenance. No quarterly or segment data.",
                "get_sec_filings": "Retrieve contextual passages from two latest annual SEC filings. For prospective growth risks choose section risks and scope all (or omit scope). The scope company filter only matches parsed financial-summary headings, not all company-relevant evidence. For historical company-wide financial explanations choose section md&a and scope company; fiscal_year filters explicit comparison headings. Unknown headings stay unknown.",
                "search_sec_filings": "Search contextual filing passages. For risk research omit scope and fiscal_year filters; risk disclosures usually lack numerical comparison headings. For historical company-wide financial trends use scope company and the latest fiscal_year; use segment for segment research. Returns explicit comparison years and headings; unknown context cannot establish causal attribution.",
            }
            for spec in specs:
                spec["description"] = descriptions.get(spec["name"], spec["description"])
        if observations is None:
            return specs
        # The model still chooses whether/what to calculate. Python only rules out
        # invalid operands and operations already executed; no question-specific routing.
        numbers = [Evidence.model_validate(e) for e in observations.values() if e.get("value") is not None]
        used = {json.dumps(c["arguments"], sort_keys=True) for c in previous_calls or []
                if c["name"] == "calculate_financial_metrics" and c["result"]["status"] == "ok"}
        choices = []
        for operation in ("operating_margin", "growth", "margin_change"):
            for a in numbers:
                for b in numbers:
                    try:
                        calculate(operation, [a, b])
                    except (ValueError, ArithmeticError):
                        continue
                    args = {"operation": operation, "evidence_ids": [a.id, b.id]}
                    if json.dumps(args, sort_keys=True) in used:
                        continue
                    choices.append({"type": "object", "additionalProperties": False,
                        "properties": {"operation": {"const": operation}, "evidence_ids": {
                            "type": "array", "prefixItems": [{"const": a.id}, {"const": b.id}],
                            "minItems": 2, "maxItems": 2}}, "required": ["operation", "evidence_ids"]})
        # Offer a batch comparison when two valid annual margin pairs exist.
        pairs = []
        for a in numbers:
            for b in numbers:
                try:
                    value, unit = calculate("operating_margin", [a, b])
                    pairs.append((a, b, a.model_copy(update={"metric": "operating_margin", "value": value, "unit": unit})))
                except (ValueError, ArithmeticError):
                    continue
        for a, b, margin in pairs:
            for c, d, previous in pairs:
                try:
                    calculate("margin_change", [margin, previous])
                except (ValueError, ArithmeticError):
                    continue
                args = {"operation": "compare_operating_margins", "evidence_ids": [a.id, b.id, c.id, d.id]}
                if json.dumps(args, sort_keys=True) not in used:
                    choices.insert(0, {"type": "object", "additionalProperties": False,
                        "properties": {"operation": {"const": "compare_operating_margins"}, "evidence_ids": {
                            "type": "array", "prefixItems": [{"const": key} for key in args["evidence_ids"]],
                            "minItems": 4, "maxItems": 4}}, "required": ["operation", "evidence_ids"]})
        if not choices:
            return [spec for spec in specs if spec["name"] != "calculate_financial_metrics"]
        next(spec for spec in specs if spec["name"] == "calculate_financial_metrics")["input_schema"] = {"anyOf": choices}
        return specs

    def normalize_call(self, call: ToolCall) -> ToolCall:
        arguments = dict(call.arguments)
        if isinstance(arguments.get("ticker"), str):
            ticker = arguments["ticker"].strip().upper()
            for key, company in self.data.items():
                if ticker == company["name"].upper():
                    ticker = key
                    break
            arguments["ticker"] = ticker
        if isinstance(arguments.get("tickers"), list):
            arguments["tickers"] = sorted(set(t.strip().upper() for t in arguments["tickers"]))
        if isinstance(arguments.get("section"), str):
            arguments["section"] = arguments["section"].strip().lower()
        # Omitted nullable arguments and explicit null mean the same request.
        if arguments.get("section") is None:
            arguments.pop("section", None)
        if arguments.get("scope") == "all":
            arguments.pop("scope", None)
        if arguments.get("fiscal_year") is None:
            arguments.pop("fiscal_year", None)
        return ToolCall(name=call.name, arguments=arguments)

    def execute(self, call: ToolCall, observations: dict[str, dict]) -> ToolResult:
        if call.name not in SPECS:
            return ToolResult(status="error", limitations=["Unknown tool"])
        try:
            args = SPECS[call.name][0].model_validate(call.arguments)
            if call.name in EXTRA_SPECS:
                if not self.sec:
                    return ToolResult(status="no_data", limitations=["This tool requires live data; fixture mode has no equivalent."])
                return execute_extended(self, call.name, args, observations)
            if isinstance(args, CalculationArgs):
                inputs = [Evidence.model_validate(observations[key]) for key in args.evidence_ids]
                if args.operation == "compare_operating_margins":
                    if len(inputs) != 4:
                        raise ValueError("Comparison requires newest income/revenue then prior income/revenue")
                    local = dict(observations)
                    records, sources, margin_ids = [], [], []
                    for pair in (args.evidence_ids[:2], args.evidence_ids[2:]):
                        result = self.execute(ToolCall(name=call.name, arguments={"operation": "operating_margin", "evidence_ids": pair}), local)
                        if result.status != "ok":
                            return result
                        records.extend(result.evidence)
                        sources.extend(result.sources)
                        margin_ids.append(result.evidence[0].id)
                        local.update({e.id: e.model_dump() for e in result.evidence})
                    change = self.execute(ToolCall(name=call.name, arguments={"operation": "margin_change", "evidence_ids": margin_ids}), local)
                    if change.status != "ok":
                        return change
                    return ToolResult(status="ok", evidence=records + change.evidence, sources=sources + change.sources)
                value, unit = calculate(args.operation, inputs)
                identifier = hashlib.sha256(json.dumps(call.model_dump(), sort_keys=True).encode()).hexdigest()[:12]
                source = Source(id=f"calc:{identifier}", title=f"Python calculation: {args.operation}", uri=f"calculation://{identifier}", synthetic=self.synthetic)
                evidence = Evidence(id=f"calc:{identifier}", source_id=source.id,
                    text=f"{'Synthetic ' if self.synthetic else ''}{inputs[0].ticker} {inputs[0].period} {args.operation} = {value} {unit}", ticker=inputs[0].ticker,
                    metric=args.operation, value=value, unit=unit, period=inputs[0].period,
                    input_ids=args.evidence_ids, operation=args.operation,
                    period_start=inputs[0].period_start, period_end=inputs[0].period_end, period_type=inputs[0].period_type)
                return ToolResult(status="ok", evidence=[evidence], sources=[source])
            if self.sec:
                return self.sec.execute(call.name, args)
            ticker = args.ticker.upper().strip()
            for key, company in self.data.items():
                if ticker == company["name"].upper():
                    ticker = key
                    break
            if ticker not in self.data:
                return ToolResult(status="no_data", limitations=["Fixture coverage: NVDA, MSFT, AMD, AAPL only"])
            company = self.data[ticker]
            source = Source(id=f"fixture:{ticker}", title=f"SYNTHETIC {ticker} fixture; not an SEC filing",
                            uri=f"fixture://companies/{ticker}")
            evidence = []
            if call.name == "get_company_profile":
                evidence.append(Evidence(id=f"{ticker}:profile", source_id=source.id, ticker=ticker,
                                         text=f"{company['name']} ({ticker}); all figures and passages are synthetic."))
            elif call.name == "get_financials":
                for row in company["financials"]:
                    for metric in ("revenue", "operating_income"):
                        evidence.append(Evidence(id=f"{ticker}:{row['period']}:{metric}", source_id=source.id,
                            ticker=ticker, text=f"Synthetic historical annual {row['period']} {metric}: {row[metric]} USD millions (reported fixture value, not a forecast)",
                            metric=metric, value=row[metric], unit="USD_millions", period=row["period"]))
            else:
                for section, text in company["sections"].items():
                    if isinstance(args, FilingArgs) and args.section and args.section.lower() != section:
                        continue
                    if isinstance(args, SearchArgs):
                        words = re.findall(r"\w+", args.query.lower())
                        if not any(word in (section + " " + text).lower() for word in words):
                            continue
                    evidence.append(Evidence(id=f"{ticker}:section:{section}", source_id=source.id,
                        ticker=ticker, text=f"SYNTHETIC [{section}]: {text}"))
            return ToolResult(status="ok" if evidence else "no_data", evidence=evidence,
                sources=[source], limitations=["Synthetic fixture data, not current company research",
                    "Only two annual revenue/operating-income periods and the following short sections exist: "
                    + ", ".join(company["sections"]) + ". No segment breakdowns, forecasts, or additional filings are available."])
        except (ValidationError, ValueError, KeyError, ArithmeticError, httpx.HTTPError) as error:
            return ToolResult(status="error", limitations=[f"Tool failed or inputs are invalid: {error}"])
