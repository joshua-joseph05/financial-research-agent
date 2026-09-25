from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Plan(Model):
    answer_type: Literal["descriptive", "historical_explanation"] = Field(default="descriptive", description="historical_explanation when the question asks why a financial measure changed; otherwise descriptive")
    companies: list[str] = Field(default_factory=list,max_length=8)
    questions: list[str] = Field(min_length=1, max_length=3)
    evidence_requirements: list[Literal["financial_values", "calculated_metrics", "filing_passages", "filing_explanations", "earnings_information", "news_headlines", "market_data", "figure_reconciliation","investing_education"]] = Field(default_factory=list, description="Required evidence categories for the original question. A why-margin-changed question needs financial_values, calculated_metrics and filing_explanations; risks usually need filing_passages. No fixed tool order.")


class ToolCall(Model):
    name: str
    arguments: dict[str, Any]


class Finding(Model):
    id: str
    text: str = Field(max_length=600, description="One atomic claim, with period and scope qualifiers; no multiple-company or multiple-period narrative")
    evidence_ids: list[str] = Field(min_length=1)
    kind: Literal["fact", "interpretation", "risk"] = "fact"
    scope: Literal["company", "segment", "unknown"] | None = None
    segment: str | None = None
    fiscal_years: list[int] = Field(default_factory=list, description="Copy exact comparison years from cited passage metadata. Never infer from filing date.")
    explains_change: bool = Field(default=False, description="True only for an explanation of the requested historical change, not a hypothetical risk.")


class Decision(Model):
    action: Literal["tool", "verify"]
    reason: str = Field(max_length=240, description="One short sentence describing the next action; no deliberation")
    tool: ToolCall | None = None
    findings: list[Finding] = Field(default_factory=list, max_length=20)
    open_questions: list[str] = Field(default_factory=list, max_length=10)


class EvidenceReview(Model):
    findings: list[Finding] = Field(max_length=4)
    open_questions: list[str] = Field(max_length=5)
    sufficient: bool = Field(description="Does collected evidence answer the requested question within available source coverage?")


class Evidence(Model):
    id: str
    source_id: str
    text: str
    ticker: str
    metric: str | None = None
    value: str | None = None
    unit: str | None = None
    period: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    period_type: str | None = None
    concept: str | None = None
    scope: Literal["company", "segment", "unknown"] | None = None
    segment: str | None = None
    fiscal_years: list[int] = Field(default_factory=list)
    section: str | None = None
    headings: list[str] = Field(default_factory=list)
    report_period: str | None = None
    input_ids: list[str] = Field(default_factory=list)
    operation: str | None = None
    reconciliation_status: Literal["matched", "mismatch", "unresolved"] | None = None


class Source(Model):
    id: str
    title: str
    uri: str
    synthetic: bool = True
    accession: str | None = None
    filed: str | None = None


class ToolResult(Model):
    status: Literal["ok", "no_data", "error"]
    evidence: list[Evidence] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ClaimCheck(Model):
    finding_id: str
    status: Literal["supported", "conflicting", "insufficient"]
    explanation: str


class Verification(Model):
    coverage: Literal["sufficient", "needs_more_evidence", "limited_by_sources"] = Field(
        description="sufficient: answers original request; needs_more_evidence: essential gap available tools can fill; limited_by_sources: essential gap unavailable in sources. Optional deeper research is not a gap.")
    unresolved_requirements: list[str] = Field(default_factory=list, max_length=6, description="Essential unanswered parts of the ORIGINAL question. A nonempty list prevents completion, regardless of coverage. Optional future research does not belong here.")
    checks: list[ClaimCheck]
    follow_up: list[str] = Field(default_factory=list, max_length=6, description="Required investigation for needs_more_evidence, otherwise optional future research suggestions")


class Synthesis(Model):
    unresolved_requirements: list[str] = Field(default_factory=list, description="Essential unanswered parts of the original question, not optional future research. Nonempty means incomplete.")
    answer: str
    finding_ids: list[str]
    limitations: list[str]
    follow_up_questions: list[str]


class GlossaryEntry(Model):
    term: str
    definition: str


class ExplainedFinding(Model):
    title: str
    explanation: str
    why_it_matters: str
    evidence_ids: list[str]
    figures: list[dict[str, str]] = Field(default_factory=list)


class BeginnerGuide(Model):
    overview: str
    status: str
    explanations: list[ExplainedFinding]
    glossary: list[GlossaryEntry]
    next_steps: list[str]


class Report(Model):
    beginner_guide: BeginnerGuide | None = None
    question: str
    answer: str
    findings: list[Finding]
    sources: list[Source]
    evidence: list[Evidence]
    limitations: list[str]
    follow_up_questions: list[str]
    stop_reason: str
    complete: bool
    as_of: str
    synthetic: bool = True
