from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse

from graph import assistant_graph, run_chat_turn, stream_chat_turn
from schemas import ChatRequest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield


app = FastAPI(title="Nipuna AI Assistant", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat")
async def chat(request: ChatRequest):
    response = await run_chat_turn(thread_id=request.thread_id, message=request.message)
    return JSONResponse(response.model_dump())


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    async def event_stream():
        async for event in stream_chat_turn(thread_id=request.thread_id, message=request.message):
            yield f"data: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

