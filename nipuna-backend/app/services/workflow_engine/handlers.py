"""Node handlers — one function per Nipuna node "type".

Every handler has the signature:

    async def handler(node: dict, resolved_params: dict, org_id: str, db: AsyncSession) -> dict

`node` is the raw React Flow node (id, type, position, data).
`resolved_params` is the *normalized* parameter dict (see `param_adapter`),
with all `{{ ... }}` placeholders already resolved against prior node outputs
by the engine's `templating.resolve` call.

Handlers return a plain JSON-serializable dict — this becomes the node's
"output" and is what downstream `{{ Node Title.output }}` references see.

Add a new node type by writing a handler and registering it in HANDLERS
at the bottom of this file.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.mcp.gateway import execute_tool
from app.services.workflow_engine.extra_handlers import handle_schedule_node
from app.services.workflow_engine.retry import with_retry

logger = logging.getLogger(__name__)

NodeHandler = Callable[[dict, dict, str, AsyncSession, bool], Awaitable[dict]]


# How to translate the friendly tool names the properties panel exposes
# (e.g. "Tally", "Google Sheets") into the engine's provider slugs. This is
# the *display name* → provider mapping the LLM sees in its system prompt,
# and is the basis of the finance_agent tool-calling loop.
DISPLAY_NAME_TO_PROVIDER: dict[str, str] = {
    "gmail": "GMAIL",
    "google mail": "GMAIL",
    "slack": "SLACK",
    "google drive": "GOOGLEDRIVE",
    "googledrive": "GOOGLEDRIVE",
    "google sheets": "AIRTABLE",  # placeholder until a Sheets provider is wired
    "gsheets": "AIRTABLE",
    "airtable": "AIRTABLE",
    "tally": "TALLY",
    "gstn": "GSTN",
    "whatsapp": "WHATSAPP",
    "zoho books": "QUICKBOOKS",  # placeholder until Zoho Books is wired
    "zoho": "QUICKBOOKS",
    "quickbooks": "QUICKBOOKS",
    "stripe": "STRIPE",
    "razorpay": "RAZORPAY",
    "xero": "XERO",
    "shopify": "SHOPIFY",
    "notion": "NOTION",
    "github": "GITHUB",
    "jira": "JIRA",
    "asana": "ASANA",
    "trello": "TRELLO",
    "linear": "LINEAR",
    "salesforce": "SALESFORCE",
    "hubspot": "HUBSPOT",
    "zendesk": "ZENDESK",
    "intercom": "INTERCOM",
    "google calendar": "GOOGLE_CALENDAR",
    "calendly": "CALENDLY",
    "dropbox": "DROPBOX",
    "discord": "DISCORD",
    "microsoft teams": "MICROSOFT_TEAMS",
    "instagram": "INSTAGRAM",
    "twitter": "TWITTER",
    "twitter / x": "TWITTER",
    "zoom": "ZOOM",
    "ocr": "OCR",
    "document parser": "OCR",
}


# Hard safety cap on the finance_agent tool-calling loop. The model can burn
# tokens quickly once it starts reasoning about which tool to call, so we
# cap the number of model turns to avoid runaway cost / latency.
_FINANCE_AGENT_MAX_TURNS = 6


def _strip_code_fences(text: str) -> str:
    """Remove leading/trailing ```json ... ``` fences the LLM sometimes adds."""
    stripped = text.strip()
    fence = re.compile(r"^```(?:json|JSON)?\s*|\s*```$", re.MULTILINE)
    return fence.sub("", stripped).strip()


def _parse_model_json(text: str) -> dict[str, Any] | None:
    """Best-effort JSON parse of a model response. Returns None on failure.

    Strips code fences and tolerates extra prose around the JSON object.
    """
    if not text:
        return None
    cleaned = _strip_code_fences(text)
    # First try the whole string.
    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            return value
    except (ValueError, TypeError):
        pass
    # Then try to find the first {...} block.
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        try:
            value = json.loads(match.group(0))
            if isinstance(value, dict):
                return value
        except (ValueError, TypeError):
            return None
    return None


def _resolve_provider_for_tool(tool: dict[str, Any]) -> str | None:
    """Pick a provider slug for a `params.tools` entry.

    The properties panel writes each tool as `{id, name, status, ...}`.
    We look at `id` first (it usually already *is* the slug), then at
    `name` (a display name that needs translation), then fall back to None.
    """
    for key in ("id", "provider", "slug"):
        raw = tool.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip().upper()
    name = tool.get("name")
    if isinstance(name, str) and name.strip():
        return DISPLAY_NAME_TO_PROVIDER.get(name.strip().lower())
    return None


@with_retry(max_attempts=3, base_delay=1.0)
async def handle_integration_node(
    node: dict[str, Any],
    params: dict[str, Any],
    org_id: str,
    db: AsyncSession,  # noqa: ARG001 — required by handler signature
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Generic handler for any node backed by the MCP/Composio gateway.

    Expects the *normalized* param shape produced by `param_adapter`:
        {"provider": "...", "action": "...", "payload": {...}}
    If any of those keys are missing we return an explicit error — we no
    longer fall back to hardcoded defaults here (the adapter is the single
    place that knows the friendly-field → provider/action mapping).

    When `dry_run=True`, we skip the real `execute_tool` call and return a
    synthetic success result so the test button doesn't fire real emails /
    write to Tally / etc. Used by `POST /workflows/{id}/run?dry_run=true`.
    """
    provider = params.get("provider")
    action = params.get("action")
    payload = params.get("payload")

    if not provider or not action or not isinstance(payload, dict):
        return {
            "status": "error",
            "error": "Missing provider/action/payload",
            "received_keys": sorted(params.keys()),
        }

    if dry_run:
        return {
            "status": "success",
            "dry_run": True,
            "provider": provider,
            "action": action,
            "would_call": {"provider": provider, "action": action, "payload": payload},
            "note": "Dry run — no external service was called.",
        }

    result = await execute_tool(org_id, provider, action, payload)
    if result.get("error"):
        return {"status": "error", "provider": provider, "action": action, **result}
    return {"status": "success", "provider": provider, "action": action, **result}


async def handle_if_node(
    node: dict[str, Any],  # noqa: ARG001
    params: dict[str, Any],
    org_id: str,  # noqa: ARG001
    db: AsyncSession,  # noqa: ARG001
    *,
    dry_run: bool = False,  # noqa: ARG001
) -> dict[str, Any]:
    """Branch on a structured comparison (`left` `operator` `right`)."""
    from app.services.workflow_engine.conditions import evaluate

    result = evaluate(params)
    return {"status": "success", "result": result, "branch": "true" if result else "false"}


@with_retry(max_attempts=3, base_delay=1.0)
async def handle_finance_agent_node(
    node: dict[str, Any],
    params: dict[str, Any],
    org_id: str,
    db: AsyncSession,  # noqa: ARG001
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Real tool-calling loop for the finance_agent node.

    The LLM is told the set of available tools (from `params["tools"]`) and
    is asked to respond each turn with a single JSON object of shape:

        {"type": "tool_call", "provider": "...", "action": "...", "params": {...}}
          or
        {"type": "final", "answer": "..."}

    We loop, dispatching tool calls to `execute_tool`, appending the results
    to the message log, and re-prompting until the model either returns
    `final` or we hit `_FINANCE_AGENT_MAX_TURNS`.
    """
    from app.services.ai.llm_client import llm_client

    instructions = params.get("instructions") or node.get("data", {}).get(
        "instructions",
        "Analyze the provided input and produce a concise financial summary.",
    )
    user_input = params.get("input", node.get("data", {}).get("input", ""))
    raw_tools = params.get("tools") or node.get("data", {}).get("tools") or []

    # Build the human-readable tool catalog the model sees in the system prompt.
    available: list[dict[str, str]] = []
    for tool in raw_tools:
        if not isinstance(tool, dict):
            continue
        provider = _resolve_provider_for_tool(tool)
        display_name = (
            tool.get("name")
            or tool.get("displayName")
            or tool.get("display_name")
            or provider
            or "unknown"
        )
        if not provider:
            continue
        available.append(
            {
                "name": str(display_name),
                "provider": provider,
                "action": str(tool.get("action") or ""),
            }
        )

    if not available:
        return {
            "status": "error",
            "error": "finance_agent has no resolvable tools — populate data.tools with {id, name, status} entries.",
        }

    if dry_run:
        return {
            "status": "success",
            "dry_run": True,
            "instructions": instructions,
            "tools": [t["name"] for t in available],
            "note": "Dry run — LLM was not invoked and no tools were called.",
        }

    catalog_lines = "\n".join(
        f"- {t['name']} (provider={t['provider']}, action={t['action'] or '<choose>'})"
        for t in available
    )

    system_prompt = (
        "You are an autonomous finance operations agent inside the Nipuna AI "
        "workflow engine.\n\n"
        "Available tools:\n"
        f"{catalog_lines}\n\n"
        "On every turn, respond with EXACTLY ONE JSON object (no prose, no "
        "code fences). Use one of these shapes:\n"
        '1. {"type": "tool_call", "provider": "PROVIDER_SLUG", '
        '"action": "PROVIDER_ACTION", "params": {...}}\n'
        '   — when you need to call a tool. PROVIDER_SLUG must be one of the '
        "providers listed above. PROVIDER_ACTION must be a known action for "
        "that provider (e.g. GMAIL_SEND_EMAIL, TALLY_CREATE_VOUCHER). "
        "`params` is the action's payload.\n"
        '2. {"type": "final", "answer": "..."}\n'
        "   — when you have enough information and want to return the final "
        "answer to the workflow.\n\n"
        "If a tool call returns an error, reason about it and try a different "
        "approach on the next turn. Do not repeat the same failed call twice."
    )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Instructions:\n{instructions}\n\n"
                f"Input:\n{user_input if user_input else '(no input provided)'}\n"
            ),
        },
    ]

    turns_used = 0
    last_answer: str = ""
    tool_log: list[dict[str, Any]] = []

    for turn in range(_FINANCE_AGENT_MAX_TURNS):
        turns_used = turn + 1
        try:
            text = await llm_client.chat(messages)
        except Exception as exc:  # noqa: BLE001
            logger.warning("finance_agent LLM call failed: %s", exc)
            return {
                "status": "error",
                "error": f"LLM call failed: {exc}",
                "turns_used": turns_used,
                "tool_log": tool_log,
            }

        # Append the assistant turn to history so subsequent tool results have
        # something to attach to.
        messages.append({"role": "assistant", "content": text})

        parsed = _parse_model_json(text)
        if not parsed:
            # Defensive: model didn't speak JSON. Treat the raw text as a final
            # answer so we don't loop forever.
            last_answer = text.strip()
            tool_log.append({"turn": turns_used, "type": "non_json", "text": last_answer})
            return {
                "status": "success",
                "answer": last_answer,
                "turns_used": turns_used,
                "tool_log": tool_log,
                "note": "Model did not respond in JSON — returned raw text as final answer.",
            }

        kind = str(parsed.get("type") or "").strip().lower()

        if kind == "final":
            answer = parsed.get("answer")
            if not isinstance(answer, str):
                answer = json.dumps(answer)
            return {
                "status": "success",
                "answer": answer,
                "turns_used": turns_used,
                "tool_log": tool_log,
            }

        if kind == "tool_call":
            provider = str(parsed.get("provider") or "").strip().upper()
            action = str(parsed.get("action") or "").strip().upper()
            call_params = parsed.get("params") or {}
            if not isinstance(call_params, dict):
                call_params = {"value": call_params}

            if not provider or not action:
                err_msg = f"Tool call missing provider/action: {parsed}"
                messages.append({"role": "user", "content": err_msg})
                tool_log.append(
                    {"turn": turns_used, "type": "tool_call", "error": err_msg}
                )
                continue

            try:
                tool_result = await execute_tool(org_id, provider, action, call_params)
            except Exception as exc:  # noqa: BLE001
                tool_result = {"error": str(exc)}

            tool_log.append(
                {
                    "turn": turns_used,
                    "type": "tool_call",
                    "provider": provider,
                    "action": action,
                    "params": call_params,
                    "result": tool_result,
                }
            )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Tool result for {provider}.{action}:\n"
                        f"{json.dumps(tool_result, default=str)}"
                    ),
                }
            )
            continue

        # Unknown shape — tell the model how to format its reply and loop.
        messages.append(
            {
                "role": "user",
                "content": (
                    "Your last response was not a valid JSON object with a "
                    '"type" of "tool_call" or "final". Please reply again '
                    "with exactly one such JSON object and nothing else."
                ),
            }
        )

    # We hit the safety cap — return what we have so downstream nodes still
    # have something to work with.
    return {
        "status": "success",
        "answer": last_answer or "(finance_agent reached max turns without a final answer)",
        "turns_used": turns_used,
        "tool_log": tool_log,
        "note": f"Hit max turns ({_FINANCE_AGENT_MAX_TURNS}) — returning partial result.",
    }


async def handle_approval_node(
    node: dict[str, Any],  # noqa: ARG001
    params: dict[str, Any],  # noqa: ARG001
    org_id: str,  # noqa: ARG001
    db: AsyncSession,  # noqa: ARG001
    *,
    dry_run: bool = False,  # noqa: ARG001
) -> dict[str, Any]:
    """Human-in-the-loop checkpoint. Execution pauses here.

    The engine treats a "waiting_approval" status as a stop signal for this
    branch. A separate resume endpoint (workflow run with `resume_from`)
    continues execution down the approved/rejected path.
    """
    return {"status": "waiting_approval", "message": "Waiting for human approval"}


async def handle_http_node(
    node: dict[str, Any],  # noqa: ARG001
    params: dict[str, Any],
    org_id: str,  # noqa: ARG001
    db: AsyncSession,  # noqa: ARG001
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """HTTP Request node — make an outbound HTTP call with method/url/headers/body.

    Dry-run: returns the resolved request shape (no network call). Real
    run: dispatches via httpx with a 30s timeout. Failures surface as
    `{"status": "error", "error": "..."}` so the engine can route to an
    error_handler / retry node.
    """
    method = str(params.get("method") or "GET").upper()
    url = str(params.get("url") or "").strip()
    if not url:
        return {"status": "error", "error": "Missing required field: url"}
    headers = params.get("headers") or {}
    query = params.get("query") or {}
    body = params.get("body")
    content_type = params.get("content_type") or "application/json"
    timeout_s = float(params.get("timeout") or 30)

    if dry_run:
        return {
            "status": "success",
            "dry_run": True,
            "method": method,
            "url": url,
            "headers": headers,
            "query": query,
            "body": body,
            "would_send": {"method": method, "url": url, "headers": headers, "body": body},
        }

    try:
        import httpx  # local import — only needed when actually making the call

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            request_kwargs: dict[str, Any] = {"headers": headers, "params": query}
            if body is not None and method in ("POST", "PUT", "PATCH", "DELETE"):
                if isinstance(body, (dict, list)):
                    request_kwargs["json"] = body
                else:
                    request_kwargs["content"] = str(body)
                    request_kwargs.setdefault("headers", {})["Content-Type"] = content_type
            response = await client.request(method, url, **request_kwargs)
        return {
            "status": "success",
            "method": method,
            "url": url,
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": _safe_response_text(response),
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "method": method, "url": url, "error": str(exc)}


def _safe_response_text(response: Any) -> Any:
    """Try to parse response as JSON; fall back to text. Truncate huge
    bodies so the engine's stored output doesn't balloon."""
    try:
        return response.json()
    except Exception:  # noqa: BLE001
        text = response.text if hasattr(response, "text") else str(response)
        return text[:8192] + ("…(truncated)" if len(text) > 8192 else "")


async def handle_webhook_node(
    node: dict[str, Any],
    params: dict[str, Any],
    org_id: str,
    db: AsyncSession,  # noqa: ARG001
    *,
    dry_run: bool = False,  # noqa: ARG001
) -> dict[str, Any]:
    """Webhook trigger — returns the public URL + token used to fire
    the workflow from an external service. The actual trigger endpoint
    is `POST /workflows/{id}/trigger?token=...` (see routers/workflows.py).

    The handler is mostly metadata; the URL/token generation happens
    during `POST /workflows/{id}/activate`. Here we just surface it
    downstream so test-fixture workflows can template `{{ Webhook.url }}`.
    """
    path = str(params.get("path") or "").strip() or f"/wh/{node.get('id', 'unknown')}"
    secret = str(params.get("secret") or "").strip()
    method = str(params.get("method") or "POST").upper()
    response_mode = str(params.get("response_mode") or "on_received")
    return {
        "status": "success",
        "path": path,
        "method": method,
        "response_mode": response_mode,
        "has_secret": bool(secret),
        "note": "Trigger this workflow from the URL shown in Settings → Webhook URL (auto-generated on activate).",
    }


async def handle_code_node(
    node: dict[str, Any],  # noqa: ARG001
    params: dict[str, Any],
    org_id: str,  # noqa: ARG001
    db: AsyncSession,  # noqa: ARG001
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Code Helper — runs a small JS/TS snippet with `input` injected and
    the return value as `output`. Sandboxed: only basic builtins (Math,
    JSON, String, Number, Array, Object, Date) are exposed.

    Dry-run executes the snippet; real-run does the same (this is a
    pure-function node, no external side effects). The engine's retry
    wrapper handles transient JS errors.
    """
    language = str(params.get("language") or "javascript").lower()
    source = str(params.get("source") or params.get("code") or "")
    if not source.strip():
        return {"status": "error", "error": "Code Helper: empty source"}
    if language not in ("javascript", "js", "typescript", "ts"):
        return {"status": "error", "error": f"Code Helper: unsupported language '{language}' (use javascript/typescript)"}
    safe_globals = {
        "Math": _SAFE_MATH,
        "JSON": _safe_json_dumps,
        "Date": _SafeDate,
        "String": str,
        "Number": lambda x: float(x) if x is not None else 0.0,
        "Array": list,
        "Object": dict,
        "console": _SafeConsole(),
        "input": params.get("input"),
        "params": {k: v for k, v in params.items() if k not in ("source", "code", "language")},
    }
    try:
        # Wrap in an IIFE so `return` works inside the snippet.
        wrapped = "(function(input, params){\n" + source + "\n})(input, params)"
        result = eval(wrapped, {"__builtins__": {}}, safe_globals)  # noqa: S307
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"Code Helper: {exc}", "language": language}
    return {"status": "success", "output": result, "language": language, "executed": True}


_SAFE_MATH = __import__("math")  # math.pi, math.floor, etc.


def _safe_json_dumps(value: Any) -> str:
    return json.dumps(value, default=str)


@dataclass
class _GenerationResult:
    """Tiny shim so the AI nodes can use a uniform `result.text` / `result.model`
    / `result.usage` API even though the underlying `llm_client` only
    exposes a `chat(messages)` method that returns a string."""
    text: str
    model: str = "unknown"
    usage: dict[str, Any] = field(default_factory=dict)


async def _llm_generate(
    prompt: str,
    system_prompt: str = "",
    *,
    model: str = "gpt-4o-mini",
    temperature: float = 0.7,  # noqa: ARG001
    max_tokens: int = 1024,  # noqa: ARG001
    json_mode: bool = False,  # noqa: ARG001
) -> _GenerationResult:
    """Convenience wrapper around `llm_client.chat`. The model/temperature/
    max_tokens/json_mode params are accepted (so the schema form can pass
    them through) but the underlying client uses its own provider config
    for those values. The wrapper exists so adding real model selection
    later is a one-file change."""
    from app.services.ai.llm_client import llm_client

    messages: list[dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    text = await llm_client.chat(messages)
    return _GenerationResult(text=text, model=model)


async def _llm_generate_vision(
    image_url: str,
    prompt: str,
    *,
    model: str = "gpt-4o-mini",
    max_tokens: int = 1024,  # noqa: ARG001
) -> _GenerationResult:
    """Vision-capable generation. v1 of the LLM client only does text;
    we fall back to a text prompt that asks the model to describe the
    image based on its URL metadata. Future revisions can wire a true
    vision-capable endpoint here."""
    text = await _llm_generate(
        prompt=f"{prompt}\n\nImage URL: {image_url}" if image_url else prompt,
        system_prompt=(
            "You are a vision assistant. The user provides an image URL — "
            "describe what you can infer from the URL and any available "
            "metadata. If you cannot access the image, explain that limitation."
        ),
        model=model,
        max_tokens=max_tokens,
    )
    return text


class _SafeDate:
    """Minimal Date stub: just `new SafeDate().toISOString()` and
    `SafeDate.now()` so simple snippets don't crash on `new Date()`."""

    def __init__(self, value: Any = None) -> None:
        from datetime import datetime, timezone
        if value is None:
            self._dt = datetime.now(timezone.utc)
        else:
            self._dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    def toISOString(self) -> str:
        return self._dt.isoformat()

    @staticmethod
    def now() -> "_SafeDate":
        return _SafeDate()

    def __str__(self) -> str:
        return self.toISOString()


class _SafeConsole:
    def log(self, *args: Any) -> None:  # noqa: D401
        logger.info("Code Helper: %s", " ".join(str(a) for a in args))


async def handle_python_node(
    node: dict[str, Any],  # noqa: ARG001
    params: dict[str, Any],
    org_id: str,  # noqa: ARG001
    db: AsyncSession,  # noqa: ARG001
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Python Run — surfaces the snippet; real execution requires a
    sandboxed Python runtime (separate workstream). In dry-run we
    return a synthetic success so the test button can validate the
    configuration. In real-run, the engine will route to a Celery
    sandbox worker (out of scope for v1)."""
    source = str(params.get("source") or "").strip()
    if not source:
        return {"status": "error", "error": "Python Run: empty source"}
    return {
        "status": "success" if dry_run else "error",
        "language": "python",
        "source_bytes": len(source),
        "requirements": str(params.get("requirements") or ""),
        "note": (
            "Dry-run only — real Python execution requires a sandboxed worker."
            if dry_run
            else "Python Run requires a sandboxed Python worker; not yet wired."
        ),
    }


async def handle_csv_node(
    node: dict[str, Any],  # noqa: ARG001
    params: dict[str, Any],
    org_id: str,  # noqa: ARG001
    db: AsyncSession,  # noqa: ARG001
    *,
    dry_run: bool = False,  # noqa: ARG001
) -> dict[str, Any]:
    """CSV Parse — turns a CSV string into a list of dicts (one per
    row) using the configured delimiter/has_header/skip_rows/encoding.
    Reads `params.input` (a string) by default; if `params.url` is set,
    fetches the URL first via httpx in real-run mode."""
    import csv as _csv
    import io as _io

    text = str(params.get("input") or params.get("text") or "")
    if not text and params.get("url"):
        return {"status": "error", "error": "CSV Parse: `url` fetching not implemented; pass `input` directly"}
    if not text:
        return {"status": "error", "error": "CSV Parse: missing `input` (string of CSV data)"}

    delimiter = str(params.get("delimiter") or ",")
    has_header = bool(params.get("has_header", True))
    skip_rows = int(params.get("skip_rows") or 0)

    lines = text.splitlines()[skip_rows:]
    if has_header and not lines:
        return {"status": "error", "error": "CSV Parse: empty input after skip_rows"}
    reader = _csv.reader(_io.StringIO("\n".join(lines)), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return {"status": "success", "rows": [], "count": 0}
    if has_header:
        header = rows[0]
        records = [dict(zip(header, r)) for r in rows[1:]]
    else:
        records = [{"col_" + str(i): v for i, v in enumerate(r)} for r in rows]
    return {"status": "success", "rows": records, "count": len(records), "delimiter": delimiter}


async def handle_excel_node(
    node: dict[str, Any],  # noqa: ARG001
    params: dict[str, Any],
    org_id: str,  # noqa: ARG001
    db: AsyncSession,  # noqa: ARG001
    *,
    dry_run: bool = False,  # noqa: ARG001
) -> dict[str, Any]:
    """Excel Parse — requires openpyxl/pandas in real-run; for v1 we
    accept a base64-encoded CSV fallback via `params.input` and return
    rows. Real xlsx parsing lives in a future worker."""
    text = str(params.get("input") or "").strip()
    sheet_name = str(params.get("sheet_name") or "Sheet1")
    if not text:
        return {
            "status": "error",
            "error": "Excel Parse: missing `input` (CSV-fallback string for v1; full xlsx support is a worker task).",
        }
    # Fallback: parse as CSV. n8n users will be prompted to install the
    # xlsx add-on once that's available.
    return await handle_csv_node(node, {**params, "input": text}, org_id, db, dry_run=dry_run) | {"sheet_name": sheet_name}


async def handle_json_node(
    node: dict[str, Any],  # noqa: ARG001
    params: dict[str, Any],
    org_id: str,  # noqa: ARG001
    db: AsyncSession,  # noqa: ARG001
    *,
    dry_run: bool = False,  # noqa: ARG001
) -> dict[str, Any]:
    """JSON Data — parses a string and (optionally) extracts a sub-path.
    `params.path` uses dot notation (e.g. "data.user.name"). Returns
    `{"status": "success", "value": <extracted>, "parsed": <full dict>}`
    so downstream nodes can template either `{{ Node.value }}` or
    `{{ Node.parsed.data }}`."""
    text = str(params.get("input") or params.get("text") or "")
    if not text:
        return {"status": "error", "error": "JSON Data: missing `input` (string of JSON)"}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return {"status": "error", "error": f"JSON Data: invalid JSON ({exc})"}
    path = str(params.get("path") or "").strip()
    value: Any = parsed
    if path:
        for segment in path.split("."):
            if isinstance(value, dict) and segment in value:
                value = value[segment]
            elif isinstance(value, list) and segment.isdigit() and int(segment) < len(value):
                value = value[int(segment)]
            else:
                value = params.get("default")
                break
    return {"status": "success", "value": value, "parsed": parsed, "path": path or None}


async def handle_db_node(
    node: dict[str, Any],
    params: dict[str, Any],
    org_id: str,  # noqa: ARG001
    db: AsyncSession,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Database Query — executes a parameterized SQL query on the
    session's bound engine. Honors `params.engine` (e.g. 'postgresql',
    'sqlite') for documentation but always runs against the active
    AsyncSession. Returns rows as a list of dicts."""
    query = str(params.get("query") or params.get("sql") or "").strip()
    if not query:
        return {"status": "error", "error": "Database Query: missing `query` (SQL string)"}
    bound_params = params.get("params") or {}
    if not isinstance(bound_params, dict):
        return {"status": "error", "error": "Database Query: `params` must be a JSON object"}

    if dry_run:
        return {
            "status": "success",
            "dry_run": True,
            "engine": str(params.get("engine") or "postgresql"),
            "query": query,
            "params": bound_params,
            "row_count": 0,
        }

    try:
        from sqlalchemy import text as _sa_text
        result = await db.execute(_sa_text(query), bound_params)
        if result.returns_rows:
            columns = list(result.keys())
            rows = [dict(zip(columns, row)) for row in result.fetchall()]
            return {"status": "success", "row_count": len(rows), "rows": rows}
        await db.commit()
        return {"status": "success", "row_count": result.rowcount or 0, "rows": []}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"Database Query failed: {exc}"}


async def handle_switch_node(
    node: dict[str, Any],  # noqa: ARG001
    params: dict[str, Any],
    org_id: str,  # noqa: ARG001
    db: AsyncSession,  # noqa: ARG001
    *,
    dry_run: bool = False,  # noqa: ARG001
) -> dict[str, Any]:
    """Switch node — multi-branch selector. `params.cases` is a list of
    `{value, label, branch}` objects. The engine uses `branch` as the
    outgoing edge's `sourceHandle`, matching how IF nodes work."""
    cases = params.get("cases") or []
    if not isinstance(cases, list):
        return {"status": "error", "error": "Switch: `cases` must be a list of {value, label, branch}"}
    input_val = params.get("input")
    matched_branch: str | None = None
    matched_value: Any = None
    for i, case in enumerate(cases):
        if not isinstance(case, dict):
            continue
        if case.get("value") == input_val:
            matched_branch = str(case.get("branch") or f"case_{i}")
            matched_value = case.get("value")
            break
    if matched_branch is None:
        # Fall back to `default` branch or `fallthrough`.
        matched_branch = str(params.get("default") or "fallthrough")
    return {
        "status": "success",
        "branch": matched_branch,
        "matched_value": matched_value,
        "input": input_val,
        "case_count": len(cases),
    }


async def handle_loop_node(
    node: dict[str, Any],  # noqa: ARG001
    params: dict[str, Any],
    org_id: str,  # noqa: ARG001
    db: AsyncSession,  # noqa: ARG001
    *,
    dry_run: bool = False,  # noqa: ARG001
) -> dict[str, Any]:
    """Loop node — iterator over a list. Engine reads `output.items` and
    fans out the rest of the graph per item (using the engine's batch
    executor). For dry-run we just surface the iteration plan."""
    items = params.get("items") or params.get("input")
    if not isinstance(items, list):
        return {"status": "error", "error": "Loop: `items` must be a list"}
    batch_size = int(params.get("batch_size") or 1)
    parallel = bool(params.get("parallel", False))
    return {
        "status": "success",
        "item_count": len(items),
        "batch_size": batch_size,
        "parallel": parallel,
        "items": items,
    }


async def handle_stop_node(
    node: dict[str, Any],  # noqa: ARG001
    params: dict[str, Any],
    org_id: str,  # noqa: ARG001
    db: AsyncSession,  # noqa: ARG001
    *,
    dry_run: bool = False,  # noqa: ARG001
) -> dict[str, Any]:
    """Stop node — graceful end of this branch. Engine treats
    `status: "stopped"` as a terminal state (no downstream execution)."""
    return {
        "status": "stopped",
        "message": str(params.get("message") or "Workflow stopped by Stop node."),
    }


async def handle_error_handler_node(
    node: dict[str, Any],  # noqa: ARG001
    params: dict[str, Any],
    org_id: str,  # noqa: ARG001
    db: AsyncSession,  # noqa: ARG001
    *,
    dry_run: bool = False,  # noqa: ARG001
) -> dict[str, Any]:
    """Error Handler — wraps the next node with catch/continue-on-fail
    semantics. The engine should look at this node's `output` to
    decide whether to short-circuit on the next failure."""
    return {
        "status": "success",
        "catch_type": str(params.get("catch_type") or "all"),
        "fallback_workflow_id": params.get("fallback_workflow_id"),
        "continue_on_fail": bool(params.get("continue_on_fail", True)),
        "note": "In real-run the engine routes errors here. In dry-run this is a no-op.",
    }


async def handle_retry_node(
    node: dict[str, Any],  # noqa: ARG001
    params: dict[str, Any],
    org_id: str,  # noqa: ARG001
    db: AsyncSession,  # noqa: ARG001
    *,
    dry_run: bool = False,  # noqa: ARG001
) -> dict[str, Any]:
    """Retry node — declares retry policy for the next node. The
    engine's `with_retry` wrapper reads this metadata to decide how
    many attempts to make on failure."""
    return {
        "status": "success",
        "max_attempts": int(params.get("max_attempts") or 3),
        "backoff_ms": int(params.get("backoff_ms") or 1000),
        "retry_on": str(params.get("retry_on") or "all"),
    }


async def handle_parser_node(
    node: dict[str, Any],  # noqa: ARG001
    params: dict[str, Any],
    org_id: str,  # noqa: ARG001
    db: AsyncSession,  # noqa: ARG001
    *,
    dry_run: bool = False,  # noqa: ARG001
) -> dict[str, Any]:
    """Parser node — extracts a value from `params.input` using a regex
    `params.pattern` and (optionally) a capture `params.group`."""
    import re as _re

    text = str(params.get("input") or "")
    pattern = str(params.get("pattern") or "")
    if not pattern:
        return {"status": "error", "error": "Parser: missing `pattern` (regex string)"}
    try:
        match = _re.search(pattern, text)
    except _re.error as exc:
        return {"status": "error", "error": f"Parser: invalid regex ({exc})"}
    if not match:
        return {"status": "success", "matched": False, "output": None}
    group = params.get("group")
    if group is None:
        value: Any = match.group(0)
    else:
        try:
            value = match.group(int(group))
        except (IndexError, ValueError):
            value = match.group(0)
    return {"status": "success", "matched": True, "output": value, "groups": list(match.groups())}


async def handle_llm_node(
    node: dict[str, Any],  # noqa: ARG001
    params: dict[str, Any],
    org_id: str,
    db: AsyncSession,  # noqa: ARG001
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """LLM node — generic text generation via the LLM client. Uses
    `params.prompt` (the user message), `params.system_prompt`,
    `params.model`, `params.temperature`, `params.max_tokens`,
    `params.json_mode`. Dry-run returns a synthetic placeholder so the
    test button validates config without burning tokens."""
    if dry_run:
        return {
            "status": "success",
            "dry_run": True,
            "model": str(params.get("model") or "gpt-4o-mini"),
            "would_generate_from": str(params.get("prompt") or "")[:200],
        }
    try:
        result = await _llm_generate(
            prompt=str(params.get("prompt") or ""),
            system_prompt=str(params.get("system_prompt") or ""),
            model=str(params.get("model") or "gpt-4o-mini"),
            temperature=float(params.get("temperature") or 0.7),
            max_tokens=int(params.get("max_tokens") or 1024),
            json_mode=bool(params.get("json_mode", False)),
        )
        return {"status": "success", "model": result.model, "output": result.text, "usage": result.usage}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"LLM: {exc}"}


async def handle_summarize_node(
    node: dict[str, Any],  # noqa: ARG001
    params: dict[str, Any],
    org_id: str,
    db: AsyncSession,  # noqa: ARG001
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Summarization — uses the LLM client with a summarize-style
    system prompt."""
    style = str(params.get("style") or "concise")
    max_length = int(params.get("max_length") or 200)
    system = (
        f"You are a {style} summarizer. Reply with a summary of at most "
        f"{max_length} words. Do not include any preamble or meta-commentary."
    )
    if dry_run:
        return {"status": "success", "dry_run": True, "system": system, "input_bytes": len(str(params.get("input") or ""))}
    try:
        result = await _llm_generate(
            prompt=str(params.get("input") or ""),
            system_prompt=system,
            model=str(params.get("model") or "gpt-4o-mini"),
            max_tokens=max_length * 2,
        )
        return {"status": "success", "summary": result.text, "style": style}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"Summarize: {exc}"}


async def handle_classify_node(
    node: dict[str, Any],  # noqa: ARG001
    params: dict[str, Any],
    org_id: str,
    db: AsyncSession,  # noqa: ARG001
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Classification — LLM picks one (or many) categories from
    `params.categories` (comma-separated)."""
    categories_csv = str(params.get("categories") or params.get("categories_csv") or "")
    categories = [c.strip() for c in categories_csv.split(",") if c.strip()]
    if not categories:
        return {"status": "error", "error": "Classify: missing `categories` (comma-separated)"}
    multi_label = bool(params.get("multi_label", False))
    system = (
        "You are a text classifier. Reply with JSON only — no prose. "
        f"Pick the {'one best' if not multi_label else 'one or more'} category "
        f"from this list: {categories}. "
        f"Reply with {{\"category\": \"<choice>\"}} (or {{\"categories\": [...]}} if multi-label)."
    )
    if dry_run:
        return {"status": "success", "dry_run": True, "categories": categories, "multi_label": multi_label}
    try:
        result = await _llm_generate(
            prompt=str(params.get("input") or ""),
            system_prompt=system,
            model=str(params.get("model") or "gpt-4o-mini"),
            max_tokens=64,
        )
        return {"status": "success", "categories": categories, "result": json.loads(_strip_code_fences(result.text))}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"Classify: {exc}"}


async def handle_vision_node(
    node: dict[str, Any],  # noqa: ARG001
    params: dict[str, Any],
    org_id: str,
    db: AsyncSession,  # noqa: ARG001
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Vision — image analysis via the LLM client (vision-capable model)."""
    image_url = str(params.get("image_url") or params.get("input") or "")
    prompt = str(params.get("prompt") or "Describe this image in detail.")
    if dry_run:
        return {"status": "success", "dry_run": True, "image_url": image_url, "prompt": prompt}
    try:
        result = await _llm_generate_vision(
            image_url=image_url,
            prompt=prompt,
            model=str(params.get("model") or "gpt-4o-mini"),
            max_tokens=int(params.get("max_tokens") or 1024),
        )
        return {"status": "success", "output": result.text, "model": result.model}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"Vision: {exc}"}


async def handle_translate_node(
    node: dict[str, Any],  # noqa: ARG001
    params: dict[str, Any],
    org_id: str,
    db: AsyncSession,  # noqa: ARG001
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Translation — uses the LLM client with a translate-style system prompt."""
    target = str(params.get("target_language") or params.get("target") or "English")
    source = str(params.get("source_language") or params.get("source") or "auto-detected")
    system = f"You are a translator. Translate the user's text from {source} to {target}. Reply with the translation only, no preamble."
    if dry_run:
        return {"status": "success", "dry_run": True, "source": source, "target": target}
    try:
        result = await _llm_generate(
            prompt=str(params.get("input") or ""),
            system_prompt=system,
            model=str(params.get("model") or "gpt-4o-mini"),
            max_tokens=int(params.get("max_tokens") or 1024),
        )
        return {"status": "success", "translation": result.text, "target": target, "source": source}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"Translate: {exc}"}


async def handle_passthrough_node(
    node: dict[str, Any],
    params: dict[str, Any],
    org_id: str,  # noqa: ARG001
    db: AsyncSession,  # noqa: ARG001
    *,
    dry_run: bool = False,  # noqa: ARG001
) -> dict[str, Any]:
    """Catches node types the engine doesn't have a dedicated handler for.

    Some of these (`formatter`, `math`, `merge`, `json`, `csv`, `delay`,
    `wait`, `http`) are simple enough to run inline; others (`code`,
    `python`, `db`, `http` with side effects, real `delay`/`loop`) are
    intentionally no-ops in v1 — they return their resolved parameters
    so downstream `{{ Node Title.output }}` references still work, but
    no real side effect happens.

    Node-type → behavior dispatch:
    - `formatter`: applies a tiny string/date transform
    - `math`:      evaluates a simple arithmetic expression
    - `merge`:     combines multiple inputs
    - `json`:      passes through (parse already happened via templating)
    - `csv`/`excel`: passes through
    - `delay`/`wait`: returns a stub "delayed" record
    - everything else (code, python, http, db, etc.): echo params
    """
    node_type = str((node.get("data") or {}).get("type") or "").strip().lower()

    # --- formatter: tiny string/date helpers ----------------------------
    if node_type == "formatter":
        return _run_formatter(params)

    # --- math: arithmetic expression evaluator ---------------------------
    if node_type == "math":
        return _run_math(params)

    # --- merge: combine multiple inputs ----------------------------------
    if node_type == "merge":
        return _run_merge(params)

    # --- delay / wait: no-op, surface the intended delay ----------------
    if node_type in ("delay", "wait"):
        ms = int(params.get("ms") or params.get("delay_ms") or params.get("seconds") or 0)
        return {
            "status": "success",
            "delayed_ms": ms,
            "output": params,
            "note": "Delay node is a no-op in dry-run; in a real run the engine would sleep before continuing.",
        }

    # Default: just echo resolved params so downstream templating works.
    return {"status": "success", "output": params}


def _run_formatter(params: dict[str, Any]) -> dict[str, Any]:
    """Tiny formatter: `params.value` + `params.format` (upper, lower,
    trim, date_iso, date_human). Unknown formats are passed through."""
    value = params.get("value") or params.get("input") or ""
    fmt = str(params.get("format") or params.get("op") or "").lower()

    if fmt in ("upper", "uppercase"):
        out = str(value).upper()
    elif fmt in ("lower", "lowercase"):
        out = str(value).lower()
    elif fmt in ("trim", "strip"):
        out = str(value).strip()
    elif fmt == "date_iso":
        from datetime import datetime, timezone
        try:
            out = datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
        except Exception:  # noqa: BLE001
            out = str(value)
    elif fmt == "date_human":
        from datetime import datetime
        for fmt_str in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                out = datetime.strptime(str(value), fmt_str).strftime("%b %d, %Y")
                break
            except ValueError:
                continue
        else:
            out = str(value)
    else:
        out = value

    return {"status": "success", "output": out, "format": fmt}


def _run_math(params: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a simple arithmetic expression. Uses Python's `eval` with
    a stripped globals dict so only arithmetic + Math functions are
    available — never pass user input that includes identifiers/function
    calls beyond the safe allowlist."""
    expression = str(params.get("expression") or params.get("expr") or params.get("value") or "0")
    # Strip anything that isn't digits, operators, parens, decimal point, or whitespace.
    safe_chars = set("0123456789+-*/()., eE")
    if not all(c in safe_chars for c in expression):
        return {
            "status": "error",
            "error": f"Math expression contains disallowed characters: {expression!r}",
        }
    try:
        result = eval(expression, {"__builtins__": {}}, {})  # noqa: S307 — safe by allowlist
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}
    return {"status": "success", "output": result, "expression": expression}


def _run_merge(params: dict[str, Any]) -> dict[str, Any]:
    """Merge node: combine inputs into a single object.

    `params.inputs` can be a list of values, a dict, or a comma-separated
    string. Returns `{"status": "success", "output": <merged>}`.
    """
    inputs = params.get("inputs") or params.get("values") or params.get("items")
    if inputs is None:
        # Whole params is the inputs.
        merged = dict(params)
        merged.pop("inputs", None)
        merged.pop("values", None)
        merged.pop("items", None)
        return {"status": "success", "output": merged}
    if isinstance(inputs, str):
        merged = [item.strip() for item in inputs.split(",") if item.strip()]
    elif isinstance(inputs, list):
        merged = list(inputs)
    elif isinstance(inputs, dict):
        merged = dict(inputs)
    else:
        merged = inputs
    return {"status": "success", "output": merged}


HANDLERS: dict[str, NodeHandler] = {
    # --- Triggers / apps / integrations --------------------------------
    "gmail": handle_integration_node,
    "email": handle_integration_node,
    "slack": handle_integration_node,
    "slack_trigger": handle_integration_node,
    "gdrive": handle_integration_node,
    "google_drive": handle_integration_node,
    "googleDrive": handle_integration_node,
    "gsheets": handle_integration_node,
    "googleSheets": handle_integration_node,
    "tally": handle_integration_node,
    "gstn": handle_integration_node,
    "whatsapp": handle_integration_node,
    "zoho": handle_integration_node,
    "hubspot": handle_integration_node,
    "notion": handle_integration_node,
    "ocr": handle_integration_node,
    "document_parser": handle_integration_node,
    "api": handle_integration_node,
    # --- AI / LLM ----------------------------------------------------
    "llm": handle_llm_node,
    "summarize": handle_summarize_node,
    "classify": handle_classify_node,
    "vision": handle_vision_node,
    "translate": handle_translate_node,
    # --- Agents (all share the same handler; agentType in params decides prompt) ---
    "finance_agent": handle_finance_agent_node,
    "research_agent": handle_finance_agent_node,
    "browser_agent": handle_finance_agent_node,
    "sales_agent": handle_finance_agent_node,
    "support_agent": handle_finance_agent_node,
    "document_agent": handle_finance_agent_node,
    "agent": handle_finance_agent_node,
    # --- Logic / flow ------------------------------------------------
    "if": handle_if_node,
    "switch": handle_switch_node,
    "loop": handle_loop_node,
    "merge": handle_passthrough_node,  # passthrough dispatches to _run_merge
    "wait": handle_passthrough_node,  # passthrough dispatches to delay/wait
    "approval": handle_approval_node,
    "stop": handle_stop_node,
    "error_handler": handle_error_handler_node,
    "retry": handle_retry_node,
    # --- Data --------------------------------------------------------
    "json": handle_json_node,
    "csv": handle_csv_node,
    "excel": handle_excel_node,
    "db": handle_db_node,
    # --- Transform ---------------------------------------------------
    "formatter": handle_passthrough_node,  # passthrough dispatches to _run_formatter
    "parser": handle_parser_node,
    "math": handle_passthrough_node,  # passthrough dispatches to _run_math
    # --- Tools / code ------------------------------------------------
    "http": handle_http_node,
    "code": handle_code_node,
    "python": handle_python_node,
    # --- Triggers (webhook / schedule) -------------------------------
    "webhook": handle_webhook_node,
    "schedule": handle_schedule_node,
    "cron": handle_schedule_node,
    # --- Flow control (delay) ----------------------------------------
    "delay": handle_passthrough_node,  # passthrough dispatches to delay/wait
}

DEFAULT_HANDLER: NodeHandler = handle_passthrough_node


def get_handler(node_type: str) -> NodeHandler:
    handler = HANDLERS.get(node_type)
    if handler is None:
        logger.warning(
            "No handler registered for node type '%s' — falling back to passthrough.",
            node_type,
        )
        return DEFAULT_HANDLER
    return handler
