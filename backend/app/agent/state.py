from typing import Any, TypedDict


class ResearchState(TypedDict):
    question: str
    as_of: str
    plan: dict[str, Any]
    observations: dict[str, dict[str, Any]]
    sources: dict[str, dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    open_questions: list[str]
    verification: dict[str, Any]
    pending_tool: dict[str, Any] | None
    iteration_count: int
    verification_count: int
    stop_reason: str
    events: list[str]
    errors: list[str]
    draft: dict[str, Any]
    report: dict[str, Any]
    feedback: str
    duplicate_count: int
    evidence_sufficient: bool
    no_progress_count: int
    new_evidence_ids: list[str]
