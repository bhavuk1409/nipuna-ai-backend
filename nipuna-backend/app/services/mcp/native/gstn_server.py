import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

GSTN_BASE_URL = "https://apisetu.gov.in/gstn/v1"
GSTN_TIMEOUT = 30.0


def _get_api_key() -> str:
    settings = get_settings()
    key = getattr(settings, "gstn_api_key", None) or ""
    return key


async def execute_gstn_action(action: str, params: dict) -> dict:
    """Route to the appropriate GSTN action handler."""
    actions = {
        "get_gst_returns": _get_gst_returns,
        "verify_gstin": _verify_gstin,
        "get_taxpayer_details": _get_taxpayer_details,
    }
    handler = actions.get(action)
    if not handler:
        logger.warning("Unknown GSTN action requested: %s", action)
        return {
            "tool_name": "gstn",
            "result": None,
            "error": f"Unknown action: {action}. Available actions: {', '.join(actions.keys())}",
        }
    api_key = _get_api_key()
    if not api_key:
        return {"tool_name": "gstn", "result": None, "error": "GSTN API key is not configured. Set GSTN_API_KEY in environment."}

    try:
        return await handler(params, api_key)
    except Exception as exc:
        logger.error("GSTN action '%s' failed unexpectedly: %s", action, exc, exc_info=True)
        return {"tool_name": "gstn", "result": None, "error": f"Internal error executing {action}: {exc}"}


async def _get_gst_returns(params: dict, api_key: str) -> dict:
    """Fetch GST returns for a GSTIN and period."""
    gstin = params.get("gstin", "")
    period = params.get("period", "")
    if not gstin or not period:
        return {"tool_name": "gstn", "result": None, "error": "Both 'gstin' and 'period' are required."}

    logger.info("Fetching GST returns for GSTIN=%s, period=%s", gstin, period)
    async with httpx.AsyncClient(timeout=GSTN_TIMEOUT) as client:
        try:
            resp = await client.get(
                f"{GSTN_BASE_URL}/returns/{gstin}/{period}",
                headers={"X-Api-Key": api_key},
            )
            resp.raise_for_status()
            data = resp.json()
            return {"tool_name": "gstn", "result": data, "error": None}
        except httpx.HTTPStatusError as exc:
            error_detail = exc.response.text[:500] if exc.response else str(exc)
            return {"tool_name": "gstn", "result": None, "error": f"GSTN API returned HTTP {exc.response.status_code}: {error_detail}"}
        except httpx.TimeoutException:
            return {"tool_name": "gstn", "result": None, "error": "GSTN API request timed out."}


async def _verify_gstin(params: dict, api_key: str) -> dict:
    """Verify a GSTIN number and return registration details."""
    gstin = params.get("gstin", "")
    if not gstin:
        return {"tool_name": "gstn", "result": None, "error": "'gstin' is required."}
    if len(gstin) != 15:
        return {"tool_name": "gstn", "result": None, "error": "GSTIN must be exactly 15 characters."}

    logger.info("Verifying GSTIN: %s", gstin)
    async with httpx.AsyncClient(timeout=GSTN_TIMEOUT) as client:
        try:
            resp = await client.get(
                f"{GSTN_BASE_URL}/search/{gstin}",
                headers={"X-Api-Key": api_key},
            )
            resp.raise_for_status()
            data = resp.json()
            return {"tool_name": "gstn", "result": data, "error": None}
        except httpx.HTTPStatusError as exc:
            error_detail = exc.response.text[:500] if exc.response else str(exc)
            return {"tool_name": "gstn", "result": None, "error": f"GSTN verification failed (HTTP {exc.response.status_code}): {error_detail}"}
        except httpx.TimeoutException:
            return {"tool_name": "gstn", "result": None, "error": "GSTN API request timed out."}


async def _get_taxpayer_details(params: dict, api_key: str) -> dict:
    """Get detailed taxpayer information for a GSTIN."""
    gstin = params.get("gstin", "")
    if not gstin:
        return {"tool_name": "gstn", "result": None, "error": "'gstin' is required."}

    logger.info("Fetching taxpayer details for GSTIN: %s", gstin)
    async with httpx.AsyncClient(timeout=GSTN_TIMEOUT) as client:
        try:
            resp = await client.get(
                f"{GSTN_BASE_URL}/taxpayer/{gstin}",
                headers={"X-Api-Key": api_key},
            )
            resp.raise_for_status()
            data = resp.json()
            return {"tool_name": "gstn", "result": data, "error": None}
        except httpx.HTTPStatusError as exc:
            error_detail = exc.response.text[:500] if exc.response else str(exc)
            return {"tool_name": "gstn", "result": None, "error": f"Failed to get taxpayer details (HTTP {exc.response.status_code}): {error_detail}"}
        except httpx.TimeoutException:
            return {"tool_name": "gstn", "result": None, "error": "GSTN API request timed out."}
