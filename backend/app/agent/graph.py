from app.agent.presentation import beginner_guide
from app.agent.coverage import CoverageTarget, coverage_status, coverage_gaps, numeric_review_ready, meaningful_requirements, calculation_gap_options
from pydantic import Field, ValidationError
from typing import Literal
from app.agent.attribution import attribution_issue, explanation_gaps, render_findings, calculation_findings, reported_financial_findings, bind_attribution, clean_citation_suffix
import json
import hashlib
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from langgraph.graph import END, START, StateGraph

from app.agent.state import ResearchState
from app.providers.llm import ResearchModel
from app.schemas import Decision, Evidence, EvidenceReview, Finding, Plan, Report, Source, Synthesis, ToolCall, Verification
from app.tools.calculations import calculate
from app.tools.registry import ToolRegistry


def merge_finding_updates(existing, updates, rejected_ids=()):
    """Do not let a reused model ID erase an unrelated, unchallenged claim."""
    merged = {f["id"]: f for f in existing}
    for update in updates:
        update = dict(update)
        key = update["id"]
        previous = merged.get(key)
        if (previous and key not in rejected_ids
                and not set(previous["evidence_ids"]) & set(update["evidence_ids"])):
            # A citation-disjoint replacement is new evidence, unless verification
            # explicitly requested a correction of the old claim.
            if any(f == {**update, "id": f["id"]} for f in merged.values()):
                continue
            index = 2
            while f"{key}_{index}" in merged:
                index += 1
            key = f"{key}_{index}"
            update["id"] = key
        merged[key] = update
    return list(merged.values())


class AssessmentAction(EvidenceReview):
    next_action: Literal["tool", "verify"]
    next_tool: ToolCall | None


class EfficientPlan(Plan):
    initial_tool: ToolCall
    coverage_targets: list[CoverageTarget] = Field(default_factory=list, max_length=8,
        description="For numerical company questions and comparisons, one entry per company with only the evidence needed by the question. Empty for questions without per-company coverage needs. Business and risk needs refer to filing sections; For financial_values, declare only requested raw financial_metrics and the minimum number of comparable annual periods in minimum_periods. This is a coverage checklist, not a fixed tool sequence.")


@dataclass(frozen=True)
class Limits:
    max_tool_calls: int = 10
    max_iterations: int = 14
    max_verifications: int = 2
    seconds: float = 480
    finalization_reserve: float = 90
    model_call_seconds: float = 90

    def __post_init__(self):
        if min(self.max_tool_calls, self.max_iterations, self.max_verifications) < 1:
            raise ValueError("Count limits must be positive")
        if self.model_call_seconds <= 0 or self.seconds <= 0 or not 0 <= self.finalization_reserve < self.seconds:
            raise ValueError("Reserve must be nonnegative and smaller than total seconds")


def initial_state(question: str) -> ResearchState:
    if not question.strip() or len(question) > 4000:
        raise ValueError("Question must contain 1–4000 characters")
    return ResearchState(question=question, as_of=datetime.now(timezone.utc).isoformat(),
        plan={}, observations={}, sources={}, tool_calls=[], findings=[], open_questions=[],
        verification={}, verification_input_hash="", pending_tool=None, iteration_count=0, verification_count=0,
        feedback="", duplicate_count=0, evidence_sufficient=False, no_progress_count=0, new_evidence_ids=[],
        stop_reason="", events=[], errors=[], draft={}, report={})


def numeric_values(text: str) -> set[Decimal]:
    return {Decimal(n.replace(",", "")) for n in re.findall(r"(?<![\w])-?\d[\d,]*(?:\.\d+)?", text)}


def numeric_check(text: str, records: list[dict]) -> bool:
    # Source identifiers can contain digits (e.g. a calculation hash); they are
    # references, not numerical claims. Strip only exact known identifiers.
    for record in records:
        text = re.sub(r"(?<!\w)" + re.escape(record["id"]) + r"(?!\w)", "", text)
    allowed = set()
    for record in records:
        allowed |= numeric_values(record["text"])
        if record.get("value") is not None:
            value = Decimal(record["value"])
            allowed |= {value, value.quantize(Decimal("0.01"))}
        if record.get("period"):
            allowed |= numeric_values(record["period"])
    return numeric_values(text) <= allowed


def structural_check(finding: dict, state: ResearchState, strict_claims=False, issuer_names=None) -> str | None:
    observations = state["observations"]
    records = {}
    visiting = set()
    def include(key):
        if key in visiting:
            raise ValueError("Cyclic calculation inputs")
        if key in records:
            return
        if key not in observations:
            raise ValueError(f"Unknown evidence ID: {key}")
        visiting.add(key)
        record = observations[key]
        for dependency in record.get("input_ids", []):
            include(dependency)
        visiting.remove(key)
        records[key] = record
    try:
        for key in finding["evidence_ids"]:
            include(key)
    except ValueError as error:
        return str(error)
    for record in records.values():
        if record["source_id"] not in state["sources"]:
            return "Evidence has no source"
        if record.get("operation"):
            try:
                inputs = [Evidence.model_validate(observations[i]) for i in record["input_ids"]]
                value, unit = calculate(record["operation"], inputs)
                if value != record["value"] or unit != record["unit"]:
                    return "Calculation failed reproduction"
            except (KeyError, ValueError, ArithmeticError):
                return "Calculation inputs are invalid"
    if strict_claims:
        from app.agent.claim_guards import passage_claim_issue, issuer_claim_issue, coverage_claim_issue, financial_trend_citation_issue
        issue = coverage_claim_issue(finding['text']) or issuer_claim_issue(finding['text'], list(records.values()), issuer_names or {})
        if issue:return issue
        issue=passage_claim_issue(finding['text'],list(records.values())) or financial_trend_citation_issue(finding['text'],list(records.values()))
        if issue:return issue
    mismatches = [e for e in observations.values() if e.get("reconciliation_status") == "mismatch"]
    for mismatch in mismatches:
        if set(mismatch.get("input_ids", [])) & records.keys() and mismatch["id"] not in finding["evidence_ids"]:
            return "Cited financial figure has an unresolved filing reconciliation mismatch"
    if records and all(key.startswith("news:") for key in records):
        if not re.search(r"\b(headline|headlines)\b", finding["text"], re.I):
            return "News-only findings must explicitly describe unverified headlines, not assert underlying events"
    has_passage = any(key.startswith("passage:") or ":section:" in key for key in records)
    if not has_passage and not any(e.get("operation") for e in records.values()):
        if re.search(r"\bcalculated\b", finding["text"], re.I):
            return "No cited calculation has been performed; use the calculation tool"
        if re.search(r"(?:filings?|reports?)\s+(?:do(?:es)? not|don't|doesn't)\s+(?:contain|provide|include)", finding["text"], re.I):
            return "Structured financial values cannot establish absence of explanations in filings; put missing evidence in open_questions"
    issue = attribution_issue(finding, observations)
    if issue:
        return issue
    if finding.get("explains_change") and "filing_explanations" in state.get("plan", {}).get("evidence_requirements", []):
        if finding.get("scope") != "company":
            return "A segment or unknown-scope passage is background, not the requested company-wide explanation; set explains_change=false"
        for record in records.values():
            if not record["id"].startswith("passage:"):
                continue
            dates = sorted({e["period_end"] for e in observations.values() if e.get("ticker") == record["ticker"] and e.get("period_end") and not e.get("operation")}, reverse=True)[:2]
            if len(dates) != 2 or finding.get("fiscal_years") != [int(d[:4]) for d in dates]:
                return "This comparison does not match the researched annual periods; treat it as background with explains_change=false, or retrieve the matching comparison"
    if not numeric_check(finding["text"], list(records.values())):
        return "Numerical claim does not match cited evidence"
    return None


def run_research(question: str, model: ResearchModel, limits: Limits | None = None,
                 registry: ToolRegistry | None = None, clock=time.monotonic, on_event=None, execution_profile="standard") -> ResearchState:
    if execution_profile not in ("standard", "efficient"):
        raise ValueError("Unknown execution profile")
    limits = limits or Limits()
    registry = registry or ToolRegistry()
    deadline = clock() + limits.seconds
    issuer_names = {}

    def canonical_findings(observations):
        from app.agent.comparisons import growth_comparison_findings
        return calculation_findings(observations) + (reported_financial_findings(observations) + growth_comparison_findings(observations) if execution_profile == "efficient" else [])

    def check_finding(finding, state):
        if execution_profile == "efficient":
            for record in state["observations"].values():
                ticker = record.get("ticker")
                if ticker and ticker not in issuer_names:
                    try:
                        _, _, name = registry.sec.resolve(ticker)
                    except (AttributeError, ValueError):
                        name = ticker
                    issuer_names[ticker] = name
        return structural_check(finding, state, execution_profile == "efficient", issuer_names)

    def context(state, phase):
        # Tool bodies already live in observations. Do not send them twice.
        common = {"question": state["question"], "plan": state["plan"], "data_mode": "synthetic fixtures" if registry.synthetic else "SEC filings"}
        if phase == "plan":
            return {"question": state["question"], "data_mode": "synthetic fixtures" if registry.synthetic else "SEC filings", "available_tools": registry.descriptions({}) if execution_profile == "efficient" else [{"name": tool["name"], "description": tool["description"]} for tool in registry.descriptions()]}
        common.update({key: state[key] for key in ("observations", "findings", "open_questions", "feedback")})
        # Keep full provenance in state/report, but avoid repeating it in every model prompt.
        common["observations"] = {key: {k: v for k, v in value.items()
            if k not in ("source_id", "concept")}
            for key, value in state["observations"].items()}
        if not registry.synthetic:
            tickers = {e["ticker"] for e in state["observations"].values()}
            common["research_periods"] = {ticker: [int(day[:4]) for day in sorted({e["period_end"] for e in state["observations"].values() if e["ticker"] == ticker and e.get("period_end") and not e.get("operation")}, reverse=True)[:2]] for ticker in tickers}
        common["data_limitations"] = list(dict.fromkeys(item for call in state["tool_calls"] for item in call["result"]["limitations"]))
        if execution_profile == "efficient":
            common["company_coverage"] = coverage_status(state["plan"], state["observations"])
        if phase == "investigate" or phase == "assess" and execution_profile == "efficient":
            common["previous_calls"] = [{"name": c["name"], "arguments": c["arguments"],
                "status": c["result"]["status"], "limitations": c["result"]["limitations"]}
                for c in state["tool_calls"]]
            common["available_tools"] = registry.descriptions(state["observations"], state["tool_calls"])
            if execution_profile=='efficient':
                options=calculation_gap_options(state['plan'],state['observations'],common['available_tools'])
                if options:
                    common['remaining_calculation_options']=options
                    common['calculation_guidance']='These valid tool calls use data already retrieved for companies still missing a declared calculation. Choose the one matching the original question rather than refetching its inputs. These are options, not executed results; other tools remain available.'
        if phase in ("assess", "verify", "synthesize"):
            common.pop("open_questions", None)
        if phase in ("verify", "synthesize"):
            common.pop("plan", None)
        if phase == "assess":
            if not registry.synthetic and execution_profile != "efficient":
                # Review new material and any explicitly rejected claims; full evidence
                # remains in state for tool choice and final recursive verification.
                needed = set(state["new_evidence_ids"])
                rejected = {c["finding_id"] for c in state["verification"].get("checks", []) if c["status"] != "supported"}
                for finding in state["findings"]:
                    if finding["id"] in rejected:
                        needed.update(finding["evidence_ids"])
                todo = list(needed)
                while todo:
                    for key in state["observations"].get(todo.pop(), {}).get("input_ids", []):
                        if key not in needed:
                            needed.add(key)
                            todo.append(key)
                common["observations"] = {key: value for key, value in common["observations"].items() if key in needed}
            if execution_profile == "efficient":
                # Full observation bodies are already present; a second inventory
                # repeats each ID, metric and date without adding evidence.
                common["assessment_scope"] = (
                    "Observation bodies include all collected evidence. Focus new claims on new_evidence_ids. "
                    "Existing findings are preserved; return only additions or corrections. "
                    "Use unused claim IDs for new findings. Correct an existing ID only for the same claim.")
            common["new_evidence_ids"] = state["new_evidence_ids"]
            common["verification"] = state["verification"]
        if phase == "verify":
            common["available_tools"] = [{"name": spec["name"], "description": spec["description"]} for spec in registry.descriptions()]
        if phase == "synthesize":
            common["stop_reason"] = state["stop_reason"]
            common["verification"] = state["verification"]
        if not registry.synthetic:
            common["observations"] = {key: {k: v for k, v in value.items() if v is not None and v != []}
                                      for key, value in common["observations"].items()}
        if phase == "verify" and execution_profile == "efficient":
            grouped=[]; calculated=[]; calculation_records={}
            canonical={f["id"]:f for f in canonical_findings(state["observations"])}
            for finding in state["findings"]:
                if canonical.get(finding["id"])==finding and not structural_check(finding,state):
                    calculated.append(finding)
                    pending=list(finding["evidence_ids"])
                    while pending:
                        key=pending.pop()
                        if key in calculation_records:
                            continue
                        record=state["observations"][key]
                        calculation_records[key]={k:v for k,v in record.items() if v is not None and v != []}
                        pending.extend(record.get("input_ids",[]))
                    continue
                records={};pending=list(finding["evidence_ids"])
                while pending:
                    key=pending.pop()
                    if key in records or key not in state["observations"]:continue
                    record=state["observations"][key]
                    records[key]={k:v for k,v in record.items() if v is not None and v != []}
                    pending.extend(record.get("input_ids",[]))
                grouped.append({"finding":finding,"cited_evidence":records})
            common.pop("observations",None)
            common.pop("findings",None)
            common["claims_to_review"]=grouped
            common["python_verified_calculations"]=calculated
            common["calculation_evidence"]=calculation_records
            common["calculation_sources"]={key:state["sources"][key] for key in sorted({r["source_id"] for r in calculation_records.values()})}
        return common

    def ask(phase, state, schema, instruction):
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError("Research deadline reached")
        if on_event:
            on_event({"phase": phase, "event": "started"})
        if execution_profile == "efficient" and phase in ("plan", "assess", "verify"):
            instruction += (" Preserve EVERY explicitly requested metric and operation from the original question. "
                "Growth is a change across periods, not a revenue level. A margin level is not a margin change. "
                "Check both sides of requested comparisons. Do not add earlier periods or extra analyses as essential requirements. "
                "If a requested part is absent, keep that specific part unresolved rather than declaring completion.")
        if execution_profile == "efficient" and phase == "verify":
            instruction += " Python has already reproduced the exact reported values and calculations in python_verified_calculations using calculation_evidence and checked their source links in calculation_sources. Count these findings when assessing answer coverage; do not request missing inputs that are present there. This validates arithmetic and lineage, not independent source truth. Review each claims_to_review finding using ONLY its own cited_evidence. Evidence attached to another finding cannot support this claim. First check whether the original question is actually answered, then verify support; a correct statement about another topic is not a complete answer."
        if execution_profile == "efficient" and phase == "plan":
            instruction += (" Also choose initial_tool from available_tools to retrieve the first required evidence, "
                "This research route needs evidence: select a retrieval tool, not a calculation. No evidence IDs exist yet. Prefer a single tool returning "
                "all requested metrics when available. For a business description retrieve section=business, scope=all; "
                "scope=company selects financial comparison headings, not general company information.")
        if execution_profile == "efficient" and phase == "investigate":
            instruction += " For business descriptions use section=business and scope=all. Do not use financial-comparison heading filters for general business questions."
        prompt = {**context(state, phase), "instruction": instruction}
        try:
            result = model.respond(phase, prompt, schema, timeout=min(remaining, limits.model_call_seconds))
        except ValidationError as error:
            if phase != "plan" or execution_profile != "efficient":
                raise
            # One repair before any retrieval; never spend an investigation loop
            # trying to satisfy a contradictory or malformed coverage checklist.
            prompt["plan_validation_errors"] = error.errors(include_url=False, include_context=False, include_input=False)
            prompt["instruction"] += " Repair the invalid plan. Name the requested metrics if financial_values is essential; otherwise omit that need. Preserve the user's actual requirements."
            remaining = deadline - clock()
            if remaining <= limits.finalization_reserve:
                raise
            result = model.respond(phase, prompt, schema, timeout=min(remaining, limits.model_call_seconds))
        if on_event:
            on_event({"phase": phase, "event": "completed", "result": result.model_dump()})
        return result

    def merged_findings(state, findings):
        # Absence from a later decision must never silently erase gathered evidence.
        if execution_profile == "efficient":
            rejected = {c["finding_id"] for c in state["verification"].get("checks", []) if c["status"] != "supported"}
            return merge_finding_updates(state["findings"],
                [f.model_dump() for f in findings if registry.synthetic or not f.id.startswith("derived:")], rejected)[-20:]
        merged = {f["id"]: f for f in state["findings"]}
        merged.update({f.id: f.model_dump() for f in findings if registry.synthetic or not f.id.startswith("derived:")})
        return list(merged.values())[-20:]

    def exhausted(state):
        if clock() >= deadline - limits.finalization_reserve:
            return "time_budget"
        if len(state["tool_calls"]) >= limits.max_tool_calls:
            return "tool_budget"
        if state["iteration_count"] >= limits.max_iterations:
            return "iteration_budget"
        return ""

    def plan(state):
        try:
            result = ask("plan", state, EfficientPlan if execution_profile == "efficient" else Plan, "First classify answer_type: historical_explanation if the user asks why a financial measure changed, otherwise descriptive. Declare nonempty evidence_requirements. Prospective risks, threats and uncertainties are descriptive research: require filing_passages, NOT filing_explanations. filing_explanations is reserved for why an observed historical financial change occurred. For named-company questions research those companies; comparisons are inferred from the question. For an open-ended sector/theme question without named companies, choose up to four relevant US-listed candidates as research hypotheses, not verified beneficiaries, and verify their relevance with tools. State this bounded scope. For conceptual investment questions no companies are required: use get_investing_guide and investing_education. Never invent current financial claims from model memory. Do not invent a user request for a specific filing section; the question controls the scope, not a presumed source. Set evidence_requirements to the categories essential for answering the original question; causal financial-trend questions require financial_values, calculated_metrics, and filing_explanations (an attributed explanation, not merely any passage). Create one to three focused evidence questions; do not fill all available slots. Do not make company-specific factual assumptions or invent evidence IDs: no evidence has been retrieved yet. Research the actual user question, without broadening it. Choose requirements supported by the available_tools in context. News queries need news_headlines, quote queries need market_data, earnings queries need earnings_information, and requests to cross-check figures need financial_values plus figure_reconciliation. Do not force unrelated annual filings into these questions. Use the declared data_mode; do not assume evidence before retrieval." + (" Classify historical_explanation ONLY when the original question explicitly asks for causes of an observed financial change. A question about warnings, possible losses, expectations or future cost pressure is descriptive even when numbers could be retrieved. Do not fetch historical financials to prove that a prospective warning is not an observed result; cite and interpret the wording of the warning. Merely saying explain or asking what remains uncertain does not request a historical cause. Comparing observed trends and asking whether one measure establishes another is descriptive; do not require a causal bridge, business overview or unrelated risks unless the original question asks for them. Fill coverage_targets for numerical questions and comparisons with every requested ticker and only relevant evidence needs. For financial_values explicitly choose financial_metrics from the question: operating_cash_flow for cash flow, operating_income for profit growth, revenue and operating_income for margins. Set minimum_periods to two for a two-year change and one for a single-year figure. Do not require unrelated revenue for profit-only or cash-flow-only questions. For non-financial needs use financial_metrics=[] and minimum_periods=1. Use calculated_metrics per company only if a quantitative comparison is needed. For a broad company comparison, split the requested coverage into business models, financial performance and disclosed risks only when relevant to the original question. Financial figures alone do not explain how the businesses differ. Record each essential part in questions; retrieve business-section passages for business descriptions and risk-section passages for risks for each requested company. A long-term perspective does not itself mean a historical-change explanation. Avoid sentiment unless the user asks about commentary or a specific expectations gap requires it." if execution_profile == "efficient" else ""))
            if result.answer_type == "historical_explanation":
                result.evidence_requirements = list(dict.fromkeys(result.evidence_requirements + ["financial_values", "calculated_metrics", "filing_explanations"]))
            if result.answer_type != "historical_explanation":
                result.evidence_requirements = list(dict.fromkeys("filing_passages" if item == "filing_explanations" else item for item in result.evidence_requirements))
            if registry.synthetic:
                result.evidence_requirements = list(dict.fromkeys("filing_passages" if item == "filing_explanations" else item for item in result.evidence_requirements))
            first = getattr(result, "initial_tool", None)
            return {"plan": result.model_dump(exclude={"initial_tool"}),
                    "pending_tool": first.model_dump() if first else None,
                    "iteration_count": int(first is not None), "open_questions": result.questions,
                    "events": ["Created research plan"]}
        except Exception as error:
            return {"stop_reason": "model_error", "errors": [f"Planning failed ({type(error).__name__})"]}

    def investigate(state):
        stop = state["stop_reason"] or exhausted(state)
        # At the tool cap, still evaluate the last result before verification.
        if stop and stop != "tool_budget":
            return {"stop_reason": stop, "pending_tool": None}
        try:
            result = ask("investigate", state, Decision,
                "Choose ONE next research action. Evidence has already been reviewed separately. For prospective risks, use risk disclosures: get_sec_filings section=risks with scope=all, or a focused keyword search without scope/year filters. A risk disclosure does not need a historical comparison heading. Company scope filters identify specific parsed financial-summary headings; they are not a filter for all relevant statements about a company. Empty filtered results do not mean risk evidence is unavailable. Read prior-call limitations and broaden restrictive filters when appropriate. "
                "If a remaining question can be answered by a tool, set action=tool and supply that tool. Never repeat a previous call. Financials supply revenue AND operating income for matching annual periods; use calculation tools to quantify changes before concluding a trend investigation. "
                "Use action=verify and tool=null when observations suffice or tools cannot fill remaining gaps. "
                "Keep findings=[] and open_questions=[]; the separate evidence review maintains them. "
                "For calculations, copy exact evidence IDs from observations. Do not guess IDs." + (" For comparisons, check coverage for EVERY requested company before deepening one company. Prefer compare_companies for compatible financial comparisons. A retrieved business passage is business coverage, not risk coverage. Missing coverage should drive the next tool choice; do not ask the user to provide evidence that an available tool can retrieve." if execution_profile == "efficient" else ""))
            if result.action == "tool" and result.tool is None:
                raise ValueError("Tool decision omitted its tool")
            if len({f.id for f in result.findings}) != len(result.findings):
                raise ValueError("Duplicate finding IDs")
            return {"findings": merged_findings(state, result.findings),
                "open_questions": result.open_questions or state["open_questions"],
                "feedback": "",
                "pending_tool": result.tool.model_dump() if result.action == "tool" and not stop else None,
                "stop_reason": stop,
                "iteration_count": state["iteration_count"] + 1,
                "events": state["events"] + [result.reason]}
        except Exception as error:
            return {"stop_reason": "model_error", "pending_tool": None,
                    "errors": state["errors"] + [f"Investigation failed ({type(error).__name__})"]}

    def execute_tool(state):
        stop = exhausted(state)
        if stop and stop != "iteration_budget":
            return {"stop_reason": stop, "pending_tool": None, "new_evidence_ids": []}
        call = ToolCall.model_validate(state["pending_tool"])
        call = registry.normalize_call(call)
        if execution_profile == "efficient" and call.name == "get_sec_filings" and call.arguments.get("section") in ("business","risks") and call.arguments.get("scope") == "company":
            # This filter means parsed financial-comparison headings, not issuer identity.
            # The ticker still restricts retrieval to the requested company.
            call = call.model_copy(update={"arguments":{k:v for k,v in call.arguments.items() if k != "scope"}})
        fingerprint = json.dumps(call.model_dump(), sort_keys=True)
        duplicates = sum(item["fingerprint"] == fingerprint for item in state["tool_calls"])
        if duplicates >= 1:
            count = state["duplicate_count"] + 1
            feedback = ("Duplicate call blocked: " + fingerprint + ". Its evidence is already in observations. "
                        "Choose a DIFFERENT tool/arguments for missing evidence, or action=verify. Do not refetch it.")
            return {"stop_reason": "repeated_tool_call" if count >= 2 else "",
                "duplicate_count": count, "pending_tool": None, "feedback": feedback,
                "events": state["events"] + ["Blocked duplicate call; retained existing evidence"]}
        start = clock()
        result = registry.execute(call, state["observations"])
        if execution_profile == "efficient" and call.name == "compare_companies":
            from app.tools.comparison_enrichment import add_revenue_growth
            result = add_revenue_growth(registry, result)
        if on_event:
            on_event({"phase": "tools", "event": "completed", "result": {"tool": call.name, "arguments": call.arguments, "status": result.status, "evidence_count": len(result.evidence), "limitations": result.limitations}})
        fresh = [e.id for e in result.evidence if state["observations"].get(e.id) != e.model_dump()]
        no_progress = 0 if fresh else state["no_progress_count"] + 1
        observations = {**state["observations"], **{e.id: e.model_dump() for e in result.evidence}}
        sources = {**state["sources"], **{s.id: s.model_dump() for s in result.sources}}
        entry = {"name": call.name, "arguments": call.arguments, "fingerprint": fingerprint,
            "duration_ms": round((clock() - start) * 1000), "result": result.model_dump()}
        generated = {} if registry.synthetic else {"findings": list({f["id"]: f for f in state["findings"] + canonical_findings(observations)}.values())}
        return {**generated, "observations": observations, "sources": sources, "pending_tool": None,
                "tool_calls": state["tool_calls"] + [entry], "new_evidence_ids": fresh,
                "no_progress_count": no_progress,
                "stop_reason": "no_new_evidence" if no_progress >= 2 else "",
                "feedback": "" if fresh else "This call produced no new evidence. Review existing findings and data limitations; do not repeat the same search approach."}

    def assess(state):
        try:
            result = ask("assess", state, AssessmentAction if execution_profile == "efficient" else EvidenceReview,
                "Write for a beginner who has never read a financial report. Use everyday words and short sentences. Explain what the source says concretely, rather than listing jargon. Spell out unfamiliar abbreviations. Keep the company, period, segment and uncertainty intact; do not invent an analogy, cause or business implication absent from the evidence. "
                "Read the collected evidence, especially new_evidence_ids, and integrate new results into a few findings relevant to the user question. "
                "Use exact observation IDs for citations. Each finding must state only what the source supports. "
                "Prefer about 35 words per claim and a complete sentence; summarize the relevant driver rather than copying every item in a disclosure. Use claim_ IDs for new filing findings; never use or change derived: IDs. Write one short statement per finding, with citations only in evidence_ids and no inline citation strings. Scope and years are separate fields, so avoid repeating them in prose. Do not restate calculation figures when reviewing passages. Return at most four short atomic NEW or CORRECTED findings; unchanged existing findings are already preserved by Python. Reuse IDs only when correcting an existing finding. Correct findings flagged by verification using the cited evidence. Respect the declared data_mode. "
                "For live passage findings, choose citations from ONE compatible scope/year group. Python attaches scope, segment and fiscal_years from the citations; do not generate these labels yourself. Split findings across different scopes, segments or comparison periods. Never infer comparison years from report_period or filing date. "
                "Set explains_change=true only when the finding explains the requested historical change; a generic risk or numeric change alone is not an explanation. A supported interpretation may connect same-period company-wide revenue, income or expense drivers to the verified margin change; the filing need not literally use the phrase operating margin. Use kind=interpretation for an inference; do not pretend a partial driver is an exhaustive bridge. "
                "Do not perform arithmetic or rewrite derived: findings; Python adds canonical calculation findings automatically. Use full four-digit years. Missing tool coverage belongs only in open_questions; never claim filings lack explanations based on numeric records. "
                "Each risk finding should describe a source-supported potential harm to the business, not just a committee, oversight process, or generic heading. Explain the potential effect on sales, costs, delivery or demand when the passage supports it. "
                "For questions about the biggest risks, identify several material disclosed risks and explain their potential impact. Do not require the issuer to rank them by size or probability; disclose that limitation. Missing an official ranking alone is not an essential unanswered question. A few excerpts may not be exhaustive, so never claim an exhaustive ranking. "
                "If a source raises a material unanswered question, list it for further investigation. "
                "Set sufficient=true when the user's question is answered within available source coverage, "
                "and open_questions=[] then. General future research suggestions do not block completion." + (
                " In this same response, choose the next action after evaluating the evidence. "
                "Use next_action=tool with next_tool to fill a specific remaining gap; use next_action=verify and next_tool=null when the requested answer is ready or available tools cannot resolve remaining gaps. "
                "Prefer get_financials when both revenue and operating income are requested; prefer compare_companies when both companies need financial comparison, since it retrieves inputs and calculates margins together. "
                "For business or risk gaps, get_sec_filings with section=business or section=risks retrieves the relevant section directly. A failed search is not proof the section is unavailable. "
                "Read company_coverage and previous_calls. Never repeat a completed call; change the section or search approach when the previous result did not answer the question. "
                "Do not add unnecessary research once the user's requested facts are supported. Keep final verification separate: you are proposing findings, not approving them. When the user asks what the evidence means, add a short direct conclusion as kind=interpretation, citing every record needed for the connection. A list of figures alone is not a comparison or explanation. You may contrast reported trends without claiming one caused the other; use existing Python calculations for arithmetic. Keep observed results separate from prospective risks. Explain remaining uncertainty in open_questions without inventing causal facts. These interpretations still require source verification."
                if execution_profile == "efficient" else ""))
            if execution_profile == "efficient":
                result.open_questions = meaningful_requirements(result.open_questions)
            accepted, issues = [], []
            canonical = {key for f in canonical_findings(state["observations"]) for key in f["evidence_ids"]}
            for finding in result.findings:
                finding = Finding.model_validate(bind_attribution(clean_citation_suffix(finding.model_dump()), state["observations"]))
                issue = check_finding(finding.model_dump(), state)
                if issue:
                    issues.append(f"Rejected proposed finding {finding.id}: {issue}. Correct attribution against the cited metadata or retrieve the missing evidence; use calculate_financial_metrics for missing calculations.")
                elif not (execution_profile == "efficient" and not registry.synthetic
                          and finding.kind == "fact" and not finding.explains_change
                          and set(finding.evidence_ids) <= canonical):
                    accepted.append(finding)
            if execution_profile == "efficient":
                issues.extend(coverage_gaps(state["plan"], state["observations"]))
            action = {}
            if isinstance(result, AssessmentAction):
                if result.sufficient and not issues and not result.open_questions:
                    # A ready answer should be checked before spending another
                    # retrieval call. Verification can still reopen genuine gaps.
                    result.next_action = "verify"
                    result.next_tool = None
                if (result.next_action == "tool") != (result.next_tool is not None):
                    # Preserve otherwise valid findings. A malformed next-action
                    # proposal must not erase evidence or execute an ambiguous tool.
                    result.next_tool = None
                    result.next_action = "verify"
                    if not result.sufficient:
                        issues.append("No valid next tool was selected. Choose a tool for the remaining question or request final verification.")
                stop = state["stop_reason"] or exhausted(state)
                action = {"pending_tool": result.next_tool.model_dump() if result.next_tool and not stop else None,
                          "assessment_action": result.next_action if not issues else "",
                          "iteration_count": state["iteration_count"] + int(result.next_tool is not None and not stop),
                          "stop_reason": stop}
            return {**action, "findings": merged_findings(state, accepted),
                "open_questions": result.open_questions + issues,
                "feedback": " ".join(issues),
                "evidence_sufficient": result.sufficient and not issues and not result.open_questions,
                "events": state["events"] + ["Reviewed new evidence"]}
        except Exception as error:
            return {"stop_reason": "assessment_error", "evidence_sufficient": False,
                "errors": state["errors"] + [f"Evidence review failed ({type(error).__name__})"]}

    def verify(state):
        signature=hashlib.sha256(json.dumps({k:state[k] for k in ("question","plan","findings","observations","sources")},sort_keys=True).encode()).hexdigest()
        if execution_profile == "efficient" and state.get("verification_input_hash")==signature:
            return {"stop_reason":"verification_no_progress", "events":state["events"]+["Retained prior verification: claims and evidence are unchanged"]}
        count = state["verification_count"] + 1
        try:
            result = ask("verify", state, Verification,
                "Assess EVERY finding against its cited passages and values. A citation alone is not support. Set coverage=sufficient when the original user question has a supported answer. Optional deeper analysis belongs in follow_up and must not change coverage. Set needs_more_evidence only for an essential unanswered part that tools can investigate, or limited_by_sources if that essential part cannot be answered with available sources. "
                "Check whether claims answer the question and whether important counterevidence is missing. Check every claim's scope, segment and fiscal-year attribution against passage headings; a driver in another segment/year is background, not the cause of the requested company-wide change. Reject any historical explanation based solely on prospective risks. "
                "A supported interpretation combining verified margin changes with matching company-wide component drivers can answer why. A filing need not literally say operating margin; an unquantified contribution of each driver is a limitation, not automatically a missing essential answer. Put essential unanswered parts in unresolved_requirements even if you select coverage=sufficient; any such requirement prevents completion. Only optional future research belongs in follow_up when coverage is sufficient. "
                "Return follow_up only for MATERIAL unanswered parts of the original user question that the available tools can investigate. Do not copy already answered open_questions. Return follow_up=[] when evidence answers the original question; optional broader research is not a blocker. "
                "For prospective risk questions, unknown numerical scope or absent comparison-year headings do not invalidate an issuer-attributed risk disclosure. Such a passage may support a risk with explains_change=false, but never a quantified company-wide historical cause. Do not demand historical financial figures to report prospective risks. "
                "For risk research, check relevance as well as literal support: a governance procedure alone (for example, board oversight) does not explain a growth risk. A disclosed prospective risk does not need a numerical probability or official severity ranking to be useful. "
                "Assess each finding on its own wording: a supported risk need not be an exhaustive list of every risk. Limited coverage belongs in follow_up, not a false rejection of supported claims. Do not equate management explanations with independently proven causality.")
            if execution_profile == "efficient":
                result.unresolved_requirements = meaningful_requirements(result.unresolved_requirements)
                result.follow_up = meaningful_requirements(result.follow_up)
            observed = list(state["observations"].values())
            present = {
                "investing_education": any(e["id"].startswith("guide:") for e in observed),
                "financial_values": any(e.get("value") is not None and not e.get("operation") and e.get("metric") != "market_close" for e in observed),
                "calculated_metrics": any(e.get("operation") in ("growth", "margin_change") for e in observed) if state["plan"].get("answer_type") == "historical_explanation" else any(e.get("operation") for e in observed),
                "earnings_information": any(e["id"].startswith("earnings:") for e in observed),
                "news_headlines": any(e["id"].startswith("news:") for e in observed),
                "market_data": any(e.get("metric") == "market_close" for e in observed),
                "figure_reconciliation": any(e.get("reconciliation_status") == "matched" for e in observed),
                "filing_passages": any(e["id"].startswith("passage:") or ":section:" in e["id"] for e in observed),
            }
            missing = [item for item in state["plan"].get("evidence_requirements", []) if item in present and not present[item]]
            if missing:
                result.coverage = "needs_more_evidence"
                result.follow_up = ["Required evidence not yet retrieved: " + ", ".join(missing)] + result.follow_up
            checks = {check.finding_id: check.model_dump() for check in result.checks}
            canonical = {f["id"]: f for f in canonical_findings(state["observations"])} if not registry.synthetic else {}
            for finding in state["findings"]:
                issue = check_finding(finding, state)
                if not issue and canonical.get(finding["id"]) == finding:
                    checks[finding["id"]] = {"finding_id": finding["id"], "status": "supported", "explanation": "Python regenerated the exact reported-value or calculation statement and checked its source/dependency chain"}
                if issue or finding["id"] not in checks:
                    checks[finding["id"]] = {"finding_id": finding["id"], "status": "insufficient",
                        "explanation": issue or "No verification returned"}
            accepted = [f for f in state["findings"] if checks[f["id"]]["status"] == "supported"]
            gaps = explanation_gaps(state, accepted)
            if execution_profile == "efficient":
                gaps.extend(coverage_gaps(state["plan"], state["observations"]))
            capabilities = {
                "investing_education": {"get_investing_guide"},
                "financial_values": {"get_financials", "get_financial_metric_history", "compare_companies"},
                "calculated_metrics": {"calculate_financial_metrics", "compare_companies", "get_financial_metric_history"},
                "earnings_information": {"get_earnings_information"},
                "news_headlines": {"get_news"},
                "market_data": {"get_market_data"},
                "figure_reconciliation": {"reconcile_financial_figures"},
                "filing_passages": {"get_sec_filings", "search_sec_filings"},
                "filing_explanations": {"get_sec_filings", "search_sec_filings"},
            }
            attempted = {call["name"] for call in state["tool_calls"]}
            missing_categories = missing + (["filing_explanations"] if explanation_gaps(state, accepted) else [])
            untried = sorted({tool for category in missing_categories if not capabilities[category] & attempted for tool in capabilities[category]})
            if untried:
                result.coverage = "needs_more_evidence"
                gaps.append("Required evidence has not been investigated with available tools: " + ", ".join(untried))
            reconciliation_gaps = ["A financial figure disagrees with the original filing; reconciliation mismatch remains unresolved." for e in state["observations"].values() if e.get("reconciliation_status") == "mismatch"]
            unresolved = list(dict.fromkeys(reconciliation_gaps + result.unresolved_requirements + gaps + missing))
            if unresolved and result.coverage == "sufficient":
                result.coverage = "needs_more_evidence"
            follow_up = list(dict.fromkeys(unresolved + result.follow_up))
            rejected = [c for c in checks.values() if c["status"] != "supported"]
            follow_up += [c["explanation"] for c in rejected]
            if not state["findings"]:
                follow_up.append("No source-backed findings were produced")
            stop = state["stop_reason"] or exhausted(state)
            needs_work = bool(rejected) or not state["findings"] or result.coverage == "needs_more_evidence"
            if not stop:
                if result.coverage == "limited_by_sources":
                    stop = "source_limit"
                elif needs_work and count >= limits.max_verifications:
                    stop = "verification_budget"
                elif not needs_work:
                    stop = "source_limit" if result.coverage == "limited_by_sources" else "evidence_sufficient"
            return {"verification": {"checks": list(checks.values()), "follow_up": follow_up, "coverage": result.coverage, "unresolved_requirements": unresolved, "untried_tools": untried},
                "open_questions": follow_up if needs_work else [], "verification_count": count, "verification_input_hash":signature, "stop_reason": stop,
                "events": state["events"] + ["Checked findings against evidence"]}
        except Exception as error:
            return {"verification": {"checks": [], "follow_up": ["Verification unavailable"]},
                "verification_count": count, "stop_reason": state["stop_reason"] or "verification_error",
                "errors": state["errors"] + [f"Verification failed ({type(error).__name__})"]}

    def synthesize(state):
        supported = {c["finding_id"] for c in state["verification"].get("checks", []) if c["status"] == "supported"}
        safe_state = {**state, "findings": [f for f in state["findings"] if f["id"] in supported]}
        if execution_profile == "efficient" and not registry.synthetic:
            # Live reports already render verified findings in Python. Preserve
            # all verified findings and unresolved requirements without a second
            # model selecting/rephrasing them. validate_report still runs.
            draft = Synthesis(answer="", finding_ids=[f["id"] for f in safe_state["findings"]],
                limitations=[], follow_up_questions=state["verification"].get("follow_up", []),
                unresolved_requirements=state["verification"].get("unresolved_requirements", []))
            if on_event:
                on_event({"phase": "synthesize", "event": "completed", "result": {"message": "Assembled verified findings"}})
            return {"draft": draft.model_dump()}
        try:
            result = ask("synthesize", safe_state, Synthesis,
                "Preserve useful supported findings even when the answer is partial; do not return an empty finding_ids list merely because a definitive ranking or complete causal explanation is unavailable. Select supported findings that answer the question, keeping quantitative comparisons AND attributed explanations. The live report renders selected findings verbatim with scope/year labels; do not rely on free prose to supply missing claims. "
                "For SEC mode answer may be an empty string because the report renderer uses your selected finding_ids; do not rewrite factual prose. In fixture mode answer using only supported findings. Preserve period and segment qualifiers. Put essential unanswered parts in unresolved_requirements, not merely in optional follow-up questions. "
                "For biggest-risk questions, preserve the supported growth-relevant risks and disclose that their severity is not quantitatively ranked. Do not discard findings or ask the user to supply SEC text when retrieval has already found it. "
                "Label synthetic data only in fixture mode; disclose missing evidence in all modes. No new numerical claims, "
                "investment recommendations, or unverified facts. Provide research follow-up questions.")
            return {"draft": result.model_dump()}
        except Exception as error:
            return {"draft": {"answer": "The run could not produce a complete synthesis. See the supported findings and limitations.",
                "finding_ids": list(supported), "limitations": ["Synthesis unavailable"], "follow_up_questions": state["open_questions"]},
                "stop_reason": state["stop_reason"] if state["stop_reason"] != "evidence_sufficient" else "synthesis_error",
                "errors": state["errors"] + [f"Synthesis failed ({type(error).__name__})"]}

    def validate_report(state):
        draft = Synthesis.model_validate(state["draft"])
        supported = {c["finding_id"] for c in state["verification"].get("checks", []) if c["status"] == "supported"}
        selected = [f for f in state["findings"] if f["id"] in supported and f["id"] in draft.finding_ids
                    and not check_finding(f, state)]
        if not registry.synthetic and "calculated_metrics" in state["plan"].get("evidence_requirements", []):
            selected_ids = {f["id"] for f in selected}
            selected = [f for f in state["findings"] if f["id"].startswith("derived:") and f["id"] in supported and f["id"] not in selected_ids and not check_finding(f, state)] + selected
        ids = set()

        def include(key):
            if key in ids:
                return
            ids.add(key)
            for input_id in state["observations"][key].get("input_ids", []):
                include(input_id)

        for finding in selected:
            for key in finding["evidence_ids"]:
                include(key)
        evidence = [state["observations"][key] for key in sorted(ids)]
        source_ids = {e["source_id"] for e in evidence}
        problems = []
        if set(draft.finding_ids) - {f["id"] for f in selected}:
            problems.append("Removed unknown or unsupported report finding references")
        answer = draft.answer if registry.synthetic else render_findings(selected, state["observations"], historical_explanation=execution_profile != "efficient" or state["plan"].get("answer_type") == "historical_explanation")
        attribution_gaps = explanation_gaps(state, selected)
        reconciliation_gaps = ["A financial figure disagrees with the original filing; reconciliation mismatch remains unresolved." for e in state["observations"].values() if e.get("reconciliation_status") == "mismatch"]
        unresolved = list(dict.fromkeys(reconciliation_gaps + state["verification"].get("unresolved_requirements", []) + draft.unresolved_requirements + attribution_gaps))
        if not selected or not numeric_check(answer, evidence):
            answer = "Research is incomplete. Review the supported findings and remaining questions below."
            problems.append("Replaced a summary with missing evidence or unmatched numerical claims")
        limitations = (["SYNTHETIC FIXTURE DATA — not actual company financial information."] if registry.synthetic else []) + [
            "Verification is a prototype: numeric/reference checks plus LLM evidence review, not independent fact verification."]
        limitations += (draft.limitations if registry.synthetic else []) + state["errors"] + problems + attribution_gaps + reconciliation_gaps
        if unresolved and not registry.synthetic:
            limitations.append("Final review identified unresolved parts of the original question; the verified findings are a partial answer. See the follow-up questions.")
        limitations += [item for call in state["tool_calls"] for item in call["result"]["limitations"]]
        limitations += [c["explanation"] for c in state["verification"].get("checks", []) if c["status"] != "supported"]
        complete = state["stop_reason"] == "evidence_sufficient" and bool(selected) and not problems and not unresolved
        report_stop = "attribution_gap" if unresolved and state["stop_reason"] == "evidence_sufficient" else state["stop_reason"]
        if not complete:
            limitations.append(f"Incomplete research: {report_stop}")
        guide = beginner_guide(selected, evidence, complete, registry.synthetic, report_stop, bool(state["observations"]))
        missing_explanation = None
        if execution_profile == "efficient" and not selected:
            from app.agent.missing_data import missing_financial_explanation
            missing_explanation = missing_financial_explanation(state)
            if missing_explanation:
                # Retrieval status and a general calculation method, not a
                # fabricated sourced finding or a completed numerical answer.
                answer = missing_explanation
                guide.overview = missing_explanation
                guide.status = "The requested numerical result is unavailable. The method and missing inputs are explained below."
        report = Report(beginner_guide=guide, question=state["question"], answer=("Synthetic fixture research: " if registry.synthetic else "") + answer,
            findings=[Finding.model_validate(f) for f in selected],
            sources=[Source.model_validate(state["sources"][key]) for key in sorted(source_ids)],
            evidence=[Evidence.model_validate(e) for e in evidence],
            limitations=list(dict.fromkeys(limitations)),
            follow_up_questions=list(dict.fromkeys((unresolved if registry.synthetic else attribution_gaps) + draft.follow_up_questions + state["open_questions"] + state["verification"].get("follow_up", []))),
            stop_reason=report_stop, complete=complete, as_of=state["as_of"], synthetic=registry.synthetic)
        if missing_explanation:
            report.follow_up_questions = ["Can the reported figures for the requested period be retrieved or supplied?"]
        return {"report": report.model_dump()}

    graph = StateGraph(ResearchState)
    for name, node in [("plan", plan), ("investigate", investigate), ("execute_tool", execute_tool),
                       ("assess", assess), ("verify", verify), ("synthesize", synthesize), ("validate_report", validate_report)]:
        graph.add_node(name, node)
    graph.add_edge(START, "plan")
    graph.add_conditional_edges("plan", lambda s: "execute_tool" if s.get("pending_tool") else "investigate")
    graph.add_conditional_edges("investigate", lambda s: "execute_tool" if s["pending_tool"] else "verify")
    def after_tool(state):
        if state["feedback"].startswith("Duplicate call blocked"):
            if execution_profile == "efficient" and not (state["stop_reason"] or exhausted(state)):
                # No evidence changed. Let the planner use the duplicate feedback
                # before paying for another review of an unfinished investigation.
                return "investigate"
            return "verify" if state["findings"] else "investigate"
        if state["new_evidence_ids"]:
            if execution_profile == "efficient" and not registry.synthetic and numeric_review_ready(state["plan"], state["observations"], state["new_evidence_ids"]):
                return "verify"  # Exact values already rendered; still review original-question coverage.
            if not registry.synthetic and all(state["observations"][key].get("operation") for key in state["new_evidence_ids"]):
                return "investigate"  # The agent evaluates computed results while choosing its next action.
            return "assess"
        return "verify" if state["findings"] or state["stop_reason"] else "investigate"
    graph.add_conditional_edges("execute_tool", after_tool)
    def after_assessment(state):
        if state["stop_reason"]:
            return "verify"
        if state.get("pending_tool"):
            return "execute_tool"
        if state["evidence_sufficient"] or state.get("assessment_action") == "verify":
            return "verify"
        return "investigate"
    graph.add_conditional_edges("assess", after_assessment)
    def after_verification(state):
        if state["stop_reason"]:
            return "synthesize"
        if state["verification"].get("untried_tools"):
            return "investigate"
        if any(c["status"] != "supported" for c in state["verification"].get("checks", [])):
            return "assess"
        return "investigate"
    graph.add_conditional_edges("verify", after_verification)
    graph.add_edge("synthesize", "validate_report")
    graph.add_edge("validate_report", END)
    return graph.compile().invoke(initial_state(question),
        config={"recursion_limit": 3 * limits.max_iterations + 2 * limits.max_verifications + 10})
