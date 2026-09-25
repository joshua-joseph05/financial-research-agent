"""Deterministic demonstration policy. This is NOT the real LLM agent."""
from app.schemas import ClaimCheck, Decision, EvidenceReview, Finding, Plan, Synthesis, ToolCall, Verification


class DemoModel:
    def respond(self, phase, context, schema, timeout):
        question = context["question"].lower()
        ticker = "MSFT" if "margin" in question or "microsoft" in question else "NVDA"
        if phase == "plan":
            return Plan(companies=[ticker], questions=[context["question"]])
        observations = context["observations"]
        findings = []

        def call(name, arguments, reason):
            return Decision(action="tool", reason=reason, tool=ToolCall(name=name, arguments=arguments),
                            findings=findings, open_questions=[context["question"]])

        if phase == "investigate":
            if ticker == "MSFT":
                if "MSFT:2025:revenue" not in observations:
                    return call("get_financials", {"ticker": ticker}, "Read synthetic annual financials")
                calculations = {e["period"]: e for e in observations.values() if e.get("metric") == "operating_margin"}
                for year in ("2024", "2025"):
                    if year not in calculations:
                        return call("calculate_financial_metrics", {"operation": "operating_margin",
                            "evidence_ids": [f"MSFT:{year}:operating_income", f"MSFT:{year}:revenue"]},
                            f"Calculate synthetic {year} operating margin")
                changes = [e for e in observations.values() if e.get("metric") == "margin_change"]
                if not changes:
                    return call("calculate_financial_metrics", {"operation": "margin_change",
                        "evidence_ids": [calculations["2025"]["id"], calculations["2024"]["id"]]},
                        "Calculate operating margin change")
                findings.append(Finding(id="margin", text=f"Synthetic operating margin increased by {changes[0]['value']} percentage points.",
                    evidence_ids=[changes[0]["id"]]))
                if "MSFT:section:md&a" not in observations:
                    return call("search_sec_filings", {"ticker": ticker, "query": "margin"}, "Look for an explanation of the margin change")
                findings.append(Finding(id="explanation", text="In the synthetic passage, management attributes margin expansion to cloud mix and expense discipline.",
                    evidence_ids=["MSFT:section:md&a"]))
            else:
                if "NVDA:section:risks" not in observations:
                    return call("get_sec_filings", {"ticker": ticker, "section": "risks"}, "Read synthetic growth risks")
                findings.append(Finding(id="risk", text="The synthetic risk disclosure identifies customer concentration and advanced packaging constraints.",
                    evidence_ids=["NVDA:section:risks"], kind="risk"))
                if "NVDA:section:supply" not in observations:
                    return call("search_sec_filings", {"ticker": ticker, "query": "packaging"},
                                "Investigate the packaging constraint identified in the first result")
                findings.append(Finding(id="supply", text="In the synthetic supply passage, packaging constraints may limit shipments despite demand.",
                    evidence_ids=["NVDA:section:supply"], kind="risk"))
            return Decision(action="verify", reason="Check collected findings", findings=findings)
        if phase == "assess":
            decision = self.respond("investigate", context, schema, timeout)
            return EvidenceReview(findings=decision.findings,
                open_questions=decision.open_questions, sufficient=decision.action == "verify")
        if phase == "verify":
            return Verification(coverage="sufficient", checks=[ClaimCheck(finding_id=f["id"], status="supported",
                explanation="Deterministic demo assertion; real mode performs LLM evidence review") for f in context["findings"]])
        return Synthesis(answer="Synthetic workflow demonstration. " + " ".join(f["text"] for f in context["findings"]),
            finding_ids=[f["id"] for f in context["findings"]],
            limitations=["Demo uses a scripted policy for two sample questions; it does not demonstrate live LLM reasoning."],
            follow_up_questions=["Do actual filings support these synthetic example patterns?"])
