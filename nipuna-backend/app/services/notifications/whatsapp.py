import asyncio
import logging

logger = logging.getLogger(__name__)


async def send_whatsapp(phone: str, message: str) -> None:
    from app.config import get_settings

    settings = get_settings()
    token = settings.meta_whatsapp_token
    phone_id = settings.meta_phone_number_id

    if not token or not phone_id:
        logger.warning("WhatsApp not configured")
        return

    import httpx

    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"https://graph.facebook.com/v19.0/{phone_id}/messages",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "messaging_product": "whatsapp",
                        "to": phone,
                        "type": "text",
                        "text": {"body": message},
                    },
                )
                if resp.status_code in (429, 500):
                    await asyncio.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                return
        except Exception as exc:
            last_exc = exc
            logger.warning("WhatsApp attempt %d failed: %s", attempt + 1, exc)

    if last_exc:
        logger.error("WhatsApp send failed after 3 retries: %s", last_exc)
