from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    thread_id: str = Field(..., description="Stable conversation thread identifier")
    message: str = Field(..., min_length=1, description="User message")


class Citation(BaseModel):
    source_name: str
    source_id: str | None = None
    source_type: str | None = None
    timestamp: datetime | None = None
    freshness: str
    evidence: str | None = None


class RetrievedContextItem(BaseModel):
    source_name: str
    source_type: str
    source_id: str
    title: str
    body: str
    timestamp: datetime
    url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    match_score: float = 0.0


class IntentResult(BaseModel):
    intent: Literal["retrieve", "tool", "general", "clarify"]
    confidence: float = Field(ge=0.0, le=1.0)
    needs_clarification: bool = False
    clarification_question: str | None = None
    domain: str | None = None
    time_scope: str | None = None
    action: str | None = None


class SourceRoute(BaseModel):
    source_name: str
    retrieval_mode: Literal["structured", "vector", "action", "unsupported"]
    operation: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    reason: str


class GroundedClaim(BaseModel):
    claim: str
    supported: bool = True
    citations: list[Citation] = Field(default_factory=list)


class AnswerPayload(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    sources_queried: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    needs_clarification: bool = False
    clarification_question: str | None = None


class ChatResponse(BaseModel):
    thread_id: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    sources_queried: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    needs_clarification: bool = False
    clarification_question: str | None = None


class GraphState(TypedDict, total=False):
    thread_id: str
    query: str
    intent: IntentResult
    route_plan: list[SourceRoute]
    sources_queried: list[str]
    retrieved_context: list[RetrievedContextItem]
    citations: list[Citation]
    grounded_claims: list[GroundedClaim]
    draft_answer: str
    final_answer: str
    confidence: float
    needs_clarification: bool
    clarification_question: str | None
    conversation_context: dict[str, Any]
    notes: list[str]
    unsupported_sources: list[str]
