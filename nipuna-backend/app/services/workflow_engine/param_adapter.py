"""Parameter adapter — translates the frontend's friendly node data into the
normalized `{provider, action, payload}` shape the engine handlers expect.

The Nipuna canvas writes user-friendly fields directly on `node.data` — for
example a Gmail node looks like:

    {
      "type": "gmail",
      "gmailAccount": "alice@example.com",
      "gmailEvent": "new_email",
      "gmailSubjectFilter": "Invoice",
    }

Downstream handlers (and `execute_tool`) only know how to consume the
normalized shape:

    {"provider": "GMAIL", "action": "GMAIL_SEND_EMAIL", "payload": {...}}

`normalize(node)` performs that translation. It also accepts a pre-populated
`data.parameters` block as an override — if both are present the structured
`data.parameters` wins so power-users / API-built workflows can opt out of
the friendly-field mapping.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# Map frontend-friendly operator strings (what the properties panel writes)
# to the engine's canonical operator tokens (consumed by `conditions.evaluate`).
_OPERATOR_MAP: dict[str, str] = {
    "gt": ">",
    "lt": "<",
    "gte": ">=",
    "lte": "<=",
    "eq": "==",
    "neq": "!=",
    "contains": "contains",
    "not_contains": "not_contains",
}


def _map_op(op: str | None) -> str:
    """Map a friendly operator token to its canonical engine operator."""
    if not op:
        return "=="
    return _OPERATOR_MAP.get(str(op).lower(), str(op))


def _coerce_str(value: Any) -> str:
    """Coerce arbitrary values into a string for textual payload fields."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _normalize_gmail(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": "GMAIL",
        "action": "GMAIL_SEND_EMAIL",
        "payload": {
            "to": _coerce_str(data.get("gmailAccount")),
            "subject": _coerce_str(data.get("gmailSubjectFilter")),
            "body": _coerce_str(data.get("gmailBody") or data.get("body")),
        },
    }


def _normalize_slack(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": "SLACK",
        "action": "SLACK_SEND_MESSAGE",
        "payload": {
            "channel": _coerce_str(data.get("slackChannel")),
            "message": _coerce_str(data.get("slackMessage")),
        },
    }


def _normalize_gdrive(data: dict[str, Any]) -> dict[str, Any]:
    raw_action = data.get("gdriveAction") or "save_attachment"
    return {
        "provider": "GOOGLEDRIVE",
        "action": f"GOOGLEDRIVE_{str(raw_action).upper()}",
        "payload": {
            "folder": _coerce_str(data.get("gdriveFolder")),
            "account": _coerce_str(data.get("gdriveAccount")),
        },
    }


def _normalize_tally(data: dict[str, Any]) -> dict[str, Any]:
    raw_action = data.get("tallyAction") or "create_voucher"
    return {
        "provider": "TALLY",
        "action": f"TALLY_{str(raw_action).upper()}",
        "payload": {
            "voucherType": _coerce_str(data.get("tallyVoucherType")),
            "connection": _coerce_str(data.get("tallyConnection")),
        },
    }


def _normalize_if(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "left": data.get("valueA"),
        "operator": _map_op(data.get("operator")),
        "right": data.get("valueB"),
    }


def _normalize_finance_agent(data: dict[str, Any]) -> dict[str, Any]:
    tools = data.get("tools") or []
    if not isinstance(tools, list):
        tools = []
    return {
        "instructions": _coerce_str(data.get("instructions")),
        "input": data.get("input", ""),
        "tools": tools,
    }


def _normalize_approval(data: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
    return {}


def _normalize_ocr(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": "OCR",
        "action": "OCR_EXTRACT",
        "payload": {
            "file_url": _coerce_str(data.get("input") or data.get("file_url")),
        },
    }


def _normalize_schedule(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "cron": _coerce_str(data.get("cron") or "0 * * * *"),
        "timezone": _coerce_str(data.get("timezone") or "UTC"),
    }


def _normalize_webhook(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": _coerce_str(data.get("path")),
        "secret": _coerce_str(data.get("secret")),
    }


# Dispatch table — node "type" -> normalizer function.
# Covers every alias the canvas might write (`gmail`/`email`, `gdrive`/
# `google_drive`/`googleDrive`, etc.) and keeps each alias pointing at the
# same canonical provider/action shape.
_NORMALIZERS: dict[str, Any] = {
    "gmail": _normalize_gmail,
    "email": _normalize_gmail,
    "slack": _normalize_slack,
    "gdrive": _normalize_gdrive,
    "google_drive": _normalize_gdrive,
    "googleDrive": _normalize_gdrive,
    "gsheets": _normalize_gdrive,  # alias to google-drive for now
    "googleSheets": _normalize_gdrive,
    "tally": _normalize_tally,
    "if": _normalize_if,
    "finance_agent": _normalize_finance_agent,
    "research_agent": _normalize_finance_agent,
    "browser_agent": _normalize_finance_agent,
    "sales_agent": _normalize_finance_agent,
    "support_agent": _normalize_finance_agent,
    "document_agent": _normalize_finance_agent,
    "agent": _normalize_finance_agent,
    "approval": _normalize_approval,
    "ocr": _normalize_ocr,
    "document_parser": _normalize_ocr,
    "schedule": _normalize_schedule,
    "cron": _normalize_schedule,
    "webhook": _normalize_webhook,
}


# Integration node types that share the same generic envelope (provider /
# action / payload). The `handle_integration_node` will dispatch them via
# the MCP gateway. The frontend's schema form populates these fields
# directly into `data.parameters` so this normalizer is rarely hit for
# them, but it's here as a safety net for hand-built graphs.
_INTEGRATION_PASSTHROUGH_TYPES: tuple[str, ...] = (
    "zoho",
    "hubspot",
    "notion",
    "whatsapp",
    "gstn",
    "api",
    "slack_trigger",
)

# Map node-type -> the provider slug the MCP gateway expects.
_PROVIDER_BY_TYPE: dict[str, str] = {
    "zoho": "QUICKBOOKS",  # placeholder until Zoho Books is wired
    "hubspot": "HUBSPOT",
    "notion": "NOTION",
    "whatsapp": "WHATSAPP",
    "gstn": "GSTN",
    "api": "CUSTOM",
    "slack_trigger": "SLACK",
}


def _normalize_integration_passthrough(data: dict[str, Any]) -> dict[str, Any]:
    """Generic integration-shape normalizer for types that don't have a
    bespoke function above (zoho, hubspot, notion, whatsapp, api, etc.).

    Reads provider/action from friendly fields or derives them from the
    node type. Everything else becomes part of the payload.
    """
    node_type = str(data.get("type") or "").strip().lower()
    provider = (
        data.get("provider")
        or _PROVIDER_BY_TYPE.get(node_type)
        or "CUSTOM"
    )
    raw_action = (
        data.get("action")
        or data.get("actionName")
        or data.get("operation")
        or "EXECUTE"
    )
    action = raw_action if str(raw_action).upper().startswith(str(provider).upper() + "_") else f"{provider}_{str(raw_action).upper()}"
    payload_keys = (
        "account", "properties", "title", "body", "to", "subject", "message",
        "channel", "folder", "file_url", "url", "method", "headers", "query",
        "spreadsheet_id", "sheet_name", "range", "database_id",
        "phone_number_id", "object_type", "organization_id", "waba_id",
        "verify_token", "bot_token", "keyword", "value", "amount",
    )
    payload = {k: data.get(k) for k in payload_keys if data.get(k) is not None}
    if not payload:
        # Fall back to the rest of the data minus the noise keys.
        payload = {k: v for k, v in data.items() if k not in ("type", "title", "subtitle", "parameters", "tools")}
    return {"provider": provider, "action": action, "payload": payload}


for _t in _INTEGRATION_PASSTHROUGH_TYPES:
    _NORMALIZERS[_t] = _normalize_integration_passthrough


def normalize(node: dict[str, Any]) -> dict[str, Any]:
    """Translate a raw React Flow node into normalized handler params.

    Behavior:
    * If `node.data.parameters` is a populated dict, it wins (and the
      derived mapping from friendly fields is merged in underneath it, so
      downstream `{{ Foo.bar }}` template resolution against either
      representation still works).
    * Otherwise we look up the node's `data.type` in `_NORMALIZERS` and
      produce the canonical shape.
    * Unknown types fall through to `{}` so handlers can decide.
    """
    data = node.get("data") or {}
    if not isinstance(data, dict):
        return {}

    node_type = str(data.get("type") or node.get("type") or "").strip()
    explicit = data.get("parameters")
    if not isinstance(explicit, dict):
        explicit = None

    normalizer = _NORMALIZERS.get(node_type)
    derived: dict[str, Any] = normalizer(data) if normalizer is not None else {}

    if explicit is not None and derived:
        # Friendly fields underneath, structured parameters on top.
        return {**derived, **explicit}
    if explicit is not None:
        return explicit
    return derived
