import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[dict] | None
    tokens_used: int


class LLMClient:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._provider: str | None = None

    @property
    def provider(self) -> str:
        if self._provider is None:
            self._provider = self._settings.llm_provider or "groq"
        return self._provider

    async def chat(self, messages: list[dict]) -> str:
        last_exc: Exception | None = None

        for attempt in range(4):
            try:
                if self.provider == "openai":
                    return await self._chat_openai(messages)
                return await self._chat_groq(messages)
            except Exception as exc:
                last_exc = exc
                logger.warning("LLM call attempt %d failed: %s", attempt + 1, exc)
                if "429" in str(exc) or (hasattr(exc, "status_code") and exc.status_code == 429):
                    wait = 4 * (2 ** attempt)
                    logger.info("Rate limited (429). Retrying in %d seconds...", wait)
                    await asyncio.sleep(wait)
                else:
                    break

        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail=f"AI service temporarily unavailable: {last_exc}")

    async def _chat_groq(self, messages: list[dict]) -> str:
        import httpx

        api_key = self._settings.groq_api_key
        model = self._settings.groq_model or "llama-3.3-70b-versatile"

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": model, "messages": messages},
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def _chat_openai(self, messages: list[dict]) -> str:
        import httpx

        api_key = self._settings.openai_api_key

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": "gpt-4o", "messages": messages},
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def chat_with_tools(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        last_exc: Exception | None = None

        for attempt in range(4):
            try:
                if self.provider == "openai":
                    return await self._chat_openai_with_tools(messages, tools)
                return await self._chat_groq_with_tools(messages, tools)
            except Exception as exc:
                last_exc = exc
                logger.warning("LLM call with tools attempt %d failed: %s", attempt + 1, exc)
                if "429" in str(exc) or (hasattr(exc, "status_code") and exc.status_code == 429):
                    wait = 4 * (2 ** attempt)
                    logger.info("Rate limited (429). Retrying in %d seconds...", wait)
                    await asyncio.sleep(wait)
                else:
                    break

        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail=f"AI service temporarily unavailable: {last_exc}")

    async def _chat_groq_with_tools(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        import httpx

        api_key = self._settings.groq_api_key
        model = self._settings.groq_model or "llama-3.3-70b-versatile"

        payload: dict[str, Any] = {"model": model, "messages": messages}
        if tools:
            payload["tools"] = [{"type": "function", "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"]
            }} for t in tools]

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            message = data["choices"][0]["message"]
            content = message.get("content")
            tool_calls = message.get("tool_calls")
            
            usage = data.get("usage", {})
            tokens_used = usage.get("total_tokens", 0)

            return LLMResponse(content=content, tool_calls=tool_calls, tokens_used=tokens_used)

    async def _chat_openai_with_tools(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        import httpx

        api_key = self._settings.openai_api_key

        payload: dict[str, Any] = {"model": "gpt-4o", "messages": messages}
        if tools:
            payload["tools"] = [{"type": "function", "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"]
            }} for t in tools]

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            message = data["choices"][0]["message"]
            content = message.get("content")
            tool_calls = message.get("tool_calls")
            
            usage = data.get("usage", {})
            tokens_used = usage.get("total_tokens", 0)

            return LLMResponse(content=content, tool_calls=tool_calls, tokens_used=tokens_used)


llm_client = LLMClient()
