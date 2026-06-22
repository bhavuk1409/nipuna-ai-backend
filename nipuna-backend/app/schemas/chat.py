from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    agent_id: str | None = Field(default=None, description="UUID of the agent")
    content: str = Field(..., min_length=1)
    conversation_id: str | None = Field(default=None, description="Resume existing conversation")
    high_intel: bool | None = Field(default=None, description="Use higher intelligence model")
    query_datasources: bool | None = Field(default=None, description="Allow AI to query integrations automatically")
    tone: str | None = Field(default=None, description="Preferred tone for the response")
    currency: str | None = Field(default=None, description="Preferred currency for financial figures")
    memory: bool | None = Field(default=None, description="Whether to use conversation memory")
    attachments: list[str] | None = Field(default=None, description="Content of text-based file attachments")


class ChatResponse(BaseModel):
    content: str
    conversation_id: str | None = Field(default=None, description="UUID of the conversation")
    tool_calls_made: int = Field(default=0, description="Number of tool invocations in this turn")


class StreamChunk(BaseModel):
    """Payload for a single SSE event."""
    type: str  # "thinking" | "tool_start" | "tool_end" | "token" | "done" | "error"
    content: str | None = None
    tool_name: str | None = None
    tool_result: str | None = None
    conversation_id: str | None = None
    tool_calls_made: int | None = None

