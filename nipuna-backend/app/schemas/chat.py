from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    agent_id: str = Field(..., description="UUID of the agent")
    content: str = Field(..., min_length=1)
    conversation_id: str | None = Field(default=None, description="Resume existing conversation")


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

