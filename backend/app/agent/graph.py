from app.agent.presentation import beginner_guide
from app.agent.attribution import attribution_issue, explanation_gaps, render_findings, calculation_findings, bind_attribution, clean_citation_suffix
import json
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
        verification={}, pending_tool=None, iteration_count=0, verification_count=0,
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


def structural_check(finding: dict, state: ResearchState) -> str | None:
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
                 registry: ToolRegistry | None = None, clock=time.monotonic, on_event=None) -> ResearchState:
    limits = limits or Limits()
    registry = registry or ToolRegistry()
    deadline = clock() + limits.seconds

    def context(state, phase):
        # Tool bodies already live in observations. Do not send them twice.
        common = {"question": state["question"], "plan": state["plan"], "data_mode": "synthetic fixtures" if registry.synthetic else "SEC filings"}
        if phase == "plan":
            return {"question": state["question"], "data_mode": "synthetic fixtures" if registry.synthetic else "SEC filings", "available_tools": [{"name": tool["name"], "description": tool["description"]} for tool in registry.descriptions()]}
        common.update({key: state[key] for key in ("observations", "findings", "open_questions", "feedback")})
        # Keep full provenance in state/report, but avoid repeating it in every model prompt.
        common["observations"] = {key: {k: v for k, v in value.items()
            if k not in ("source_id", "concept")}
            for key, value in state["observations"].items()}
        if not registry.synthetic:
            tickers = {e["ticker"] for e in state["observations"].values()}
            common["research_periods"] = {ticker: [int(day[:4]) for day in sorted({e["period_end"] for e in state["observations"].values() if e["ticker"] == ticker and e.get("period_end") and not e.get("operation")}, reverse=True)[:2]] for ticker in tickers}
        common["data_limitations"] = list(dict.fromkeys(item for call in state["tool_calls"] for item in call["result"]["limitations"]))
        if phase == "investigate":
            common["previous_calls"] = [{"name": c["name"], "arguments": c["arguments"],
                "status": c["result"]["status"], "limitations": c["result"]["limitations"]}
                for c in state["tool_calls"]]
            common["available_tools"] = registry.descriptions(state["observations"], state["tool_calls"])
        if phase in ("assess", "verify", "synthesize"):
            common.pop("open_questions", None)
        if phase in ("verify", "synthesize"):
            common.pop("plan", None)
        if phase == "assess":
            if not registry.synthetic:
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
        return common

    def ask(phase, state, schema, instruction):
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError("Research deadline reached")
        if on_event:
            on_event({"phase": phase, "event": "started"})
        result = model.respond(phase, {**context(state, phase), "instruction": instruction},
                               schema, timeout=min(remaining, limits.model_call_seconds))
        if on_event:
            on_event({"phase": phase, "event": "completed", "result": result.model_dump()})
        return result

    def merged_findings(state, findings):
        # Absence from a later decision must never silently erase gathered evidence.
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
            result = ask("plan", state, Plan, "First classify answer_type: historical_explanation if the user asks why a financial measure changed, otherwise descriptive. Declare nonempty evidence_requirements. Prospective risks, threats and uncertainties are descriptive research: require filing_passages, NOT filing_explanations. filing_explanations is reserved for why an observed historical financial change occurred. For named-company questions research those companies; comparisons are inferred from the question. For an open-ended sector/theme question without named companies, choose up to four relevant US-listed candidates as research hypotheses, not verified beneficiaries, and verify their relevance with tools. State this bounded scope. For conceptual investment questions no companies are required: use get_investing_guide and investing_education. Never invent current financial claims from model memory. Do not invent a user request for a specific filing section; the question controls the scope, not a presumed source. Set evidence_requirements to the categories essential for answering the original question; causal financial-trend questions require financial_values, calculated_metrics, and filing_explanations (an attributed explanation, not merely any passage). Create one to three focused evidence questions; do not fill all available slots. Do not make company-specific factual assumptions or invent evidence IDs: no evidence has been retrieved yet. Research the actual user question, without broadening it. Choose requirements supported by the available_tools in context. News queries need news_headlines, quote queries need market_data, earnings queries need earnings_information, and requests to cross-check figures need financial_values plus figure_reconciliation. Do not force unrelated annual filings into these questions. Use the declared data_mode; do not assume evidence before retrieval.")
            if result.answer_type == "historical_explanation":
                result.evidence_requirements = list(dict.fromkeys(result.evidence_requirements + ["financial_values", "calculated_metrics", "filing_explanations"]))
            if result.answer_type != "historical_explanation":
                result.evidence_requirements = list(dict.fromkeys("filing_passages" if item == "filing_explanations" else item for item in result.evidence_requirements))
            if registry.synthetic:
                result.evidence_requirements = list(dict.fromkeys("filing_passages" if item == "filing_explanations" else item for item in result.evidence_requirements))
            return {"plan": result.model_dump(), "open_questions": result.questions,
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
                "For calculations, copy exact evidence IDs from observations. Do not guess IDs.")
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
        if on_event:
            on_event({"phase": "tools", "event": "completed", "result": {"tool": call.name, "arguments": call.arguments, "status": result.status, "evidence_count": len(result.evidence), "limitations": result.limitations}})
        fresh = [e.id for e in result.evidence if state["observations"].get(e.id) != e.model_dump()]
        no_progress = 0 if fresh else state["no_progress_count"] + 1
        observations = {**state["observations"], **{e.id: e.model_dump() for e in result.evidence}}
        sources = {**state["sources"], **{s.id: s.model_dump() for s in result.sources}}
        entry = {"name": call.name, "arguments": call.arguments, "fingerprint": fingerprint,
            "duration_ms": round((clock() - start) * 1000), "result": result.model_dump()}
        generated = {} if registry.synthetic else {"findings": list({f["id"]: f for f in state["findings"] + calculation_findings(observations)}.values())}
        return {**generated, "observations": observations, "sources": sources, "pending_tool": None,
                "tool_calls": state["tool_calls"] + [entry], "new_evidence_ids": fresh,
                "no_progress_count": no_progress,
                "stop_reason": "no_new_evidence" if no_progress >= 2 else "",
                "feedback": "" if fresh else "This call produced no new evidence. Review existing findings and data limitations; do not repeat the same search approach."}

    def assess(state):
        try:
            result = ask("assess", state, EvidenceReview,
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
                "and open_questions=[] then. General future research suggestions do not block completion.")
            accepted, issues = [], []
            for finding in result.findings:
                finding = Finding.model_validate(bind_attribution(clean_citation_suffix(finding.model_dump()), state["observations"]))
                issue = structural_check(finding.model_dump(), state)
                if issue:
                    issues.append(f"Rejected proposed finding {finding.id}: {issue}. Correct attribution against the cited metadata or retrieve the missing evidence; use calculate_financial_metrics for missing calculations.")
                else:
                    accepted.append(finding)
            return {"findings": merged_findings(state, accepted),
                "open_questions": result.open_questions + issues,
                "feedback": " ".join(issues),
                "evidence_sufficient": result.sufficient and not issues and not result.open_questions,
                "events": state["events"] + ["Reviewed new evidence"]}
        except Exception as error:
            return {"stop_reason": "assessment_error", "evidence_sufficient": False,
                "errors": state["errors"] + [f"Evidence review failed ({type(error).__name__})"]}

    def verify(state):
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
            canonical = {f["id"]: f for f in calculation_findings(state["observations"])} if not registry.synthetic else {}
            for finding in state["findings"]:
                issue = structural_check(finding, state)
                if not issue and canonical.get(finding["id"]) == finding:
                    checks[finding["id"]] = {"finding_id": finding["id"], "status": "supported", "explanation": "Python regenerated the statement and reproduced its full calculation dependency chain"}
                if issue or finding["id"] not in checks:
                    checks[finding["id"]] = {"finding_id": finding["id"], "status": "insufficient",
                        "explanation": issue or "No verification returned"}
            accepted = [f for f in state["findings"] if checks[f["id"]]["status"] == "supported"]
            gaps = explanation_gaps(state, accepted)
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
            missing_categories = missing + (["filing_explanations"] if gaps else [])
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
                "open_questions": follow_up if needs_work else [], "verification_count": count, "stop_reason": stop,
                "events": state["events"] + ["Checked findings against evidence"]}
        except Exception as error:
            return {"verification": {"checks": [], "follow_up": ["Verification unavailable"]},
                "verification_count": count, "stop_reason": state["stop_reason"] or "verification_error",
                "errors": state["errors"] + [f"Verification failed ({type(error).__name__})"]}

    def synthesize(state):
        supported = {c["finding_id"] for c in state["verification"].get("checks", []) if c["status"] == "supported"}
        safe_state = {**state, "findings": [f for f in state["findings"] if f["id"] in supported]}
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
                    and not structural_check(f, state)]
        if not registry.synthetic and "calculated_metrics" in state["plan"].get("evidence_requirements", []):
            selected_ids = {f["id"] for f in selected}
            selected = [f for f in state["findings"] if f["id"].startswith("derived:") and f["id"] in supported and f["id"] not in selected_ids and not structural_check(f, state)] + selected
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
        answer = draft.answer if registry.synthetic else render_findings(selected, state["observations"])
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
        report = Report(beginner_guide=beginner_guide(selected, evidence, complete, registry.synthetic, report_stop, bool(state["observations"])), question=state["question"], answer=("Synthetic fixture research: " if registry.synthetic else "") + answer,
            findings=[Finding.model_validate(f) for f in selected],
            sources=[Source.model_validate(state["sources"][key]) for key in sorted(source_ids)],
            evidence=[Evidence.model_validate(e) for e in evidence],
            limitations=list(dict.fromkeys(limitations)),
            follow_up_questions=list(dict.fromkeys((unresolved if registry.synthetic else attribution_gaps) + draft.follow_up_questions + state["open_questions"] + state["verification"].get("follow_up", []))),
            stop_reason=report_stop, complete=complete, as_of=state["as_of"], synthetic=registry.synthetic)
        return {"report": report.model_dump()}

    graph = StateGraph(ResearchState)
    for name, node in [("plan", plan), ("investigate", investigate), ("execute_tool", execute_tool),
                       ("assess", assess), ("verify", verify), ("synthesize", synthesize), ("validate_report", validate_report)]:
        graph.add_node(name, node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "investigate")
    graph.add_conditional_edges("investigate", lambda s: "execute_tool" if s["pending_tool"] else "verify")
    def after_tool(state):
        if state["feedback"].startswith("Duplicate call blocked"):
            return "verify" if state["findings"] else "investigate"
        if state["new_evidence_ids"]:
            if not registry.synthetic and all(state["observations"][key].get("operation") for key in state["new_evidence_ids"]):
                return "investigate"  # The agent evaluates computed results while choosing its next action.
            return "assess"
        return "verify" if state["findings"] or state["stop_reason"] else "investigate"
    graph.add_conditional_edges("execute_tool", after_tool)
    graph.add_conditional_edges("assess", lambda s: "verify" if s["evidence_sufficient"] or s["stop_reason"] else "investigate")
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
