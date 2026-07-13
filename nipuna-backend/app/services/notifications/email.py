import asyncio
import logging

logger = logging.getLogger(__name__)


async def send_email(
    to: str,
    subject: str,
    html: str,
    from_email: str = "alerts@nipunaai.in",
    attachments: list[dict] | None = None,
) -> None:
    from app.config import get_settings

    settings = get_settings()
    api_key = settings.resend_api_key

    if not api_key:
        logger.warning("Resend email not configured")
        return

    import httpx

    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            payload = {
                "from": from_email,
                "to": to,
                "subject": subject,
                "html": html,
            }
            if attachments:
                payload["attachments"] = attachments

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                if resp.status_code >= 500:
                    await asyncio.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                return
        except Exception as exc:
            last_exc = exc
            logger.warning("Email attempt %d failed: %s", attempt + 1, exc)

    if last_exc:
        logger.error("Email send failed after 3 retries: %s", last_exc)
