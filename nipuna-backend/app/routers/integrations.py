import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID


from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse, FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_org, get_current_user
from app.models.alert import Alert
from app.models.integration import Integration
from app.models.organization import Organization
from app.models.user import User
from app.schemas.integration import (
    IntegrationConnectRequest,
    IntegrationInitializeRequest,
    IntegrationListResponse,
    IntegrationResponse,
    AvailableIntegrationResponse,
)
from app.utils.audit import log_action

from app.utils.encryption import encrypt
from app.services.mcp.gateway import AVAILABLE_PROVIDERS, composio_gateway, check_tool_connectivity

router = APIRouter(prefix="/integrations", tags=["integrations"])




_DESKTOP_DIST_DEFAULTS: dict[str, tuple[str, str]] = {
    "mac": ("Nipuna Desktop-0.1.0-arm64.dmg", "application/octet-stream"),
    "win": ("Nipuna Desktop Setup 0.1.0.exe", "application/octet-stream"),
}


@router.get("/download/{os}")
async def download_desktop_app(os: str):
    """Serve the Nipuna Desktop installer binary.

    The base directory is resolved from the DESKTOP_DIST_DIR environment
    variable so the path is not hardcoded to any developer's home directory.
    Falls back to a path relative to the project root for local development.
    """
    import os as os_module
    from pathlib import Path

    os_key = os.lower()
    if os_key not in _DESKTOP_DIST_DEFAULTS:
        raise HTTPException(status_code=400, detail=f"Unsupported OS: '{os_key}'. Valid values: mac, win")

    filename, media_type = _DESKTOP_DIST_DEFAULTS[os_key]

    # Prefer an explicit env override (required in production)
    dist_dir_env = os_module.getenv("DESKTOP_DIST_DIR")
    if dist_dir_env:
        dist_dir = Path(dist_dir_env)
    else:
        # Local fallback: <repo-root>/nipuna-desktop/dist
        dist_dir = Path(__file__).resolve().parents[3] / "nipuna-desktop" / "dist"

    file_path = dist_dir / filename
    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Installer not found. Set DESKTOP_DIST_DIR env var or build the desktop app first.",
        )

    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type=media_type,
    )

@router.get("", response_model=IntegrationListResponse)
async def list_integrations(
    org: Organization = Depends(get_current_org),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> IntegrationListResponse:
    connected_result = await db.execute(
        select(func.count(Integration.id)).where(
            Integration.org_id == org.id,
            Integration.status == "connected",
        )
    )
    connected = connected_result.scalar() or 0

    pending_result = await db.execute(
        select(func.count(Integration.id)).where(
            Integration.org_id == org.id,
            Integration.status == "pending",
        )
    )
    pending = pending_result.scalar() or 0

    sync_health_result = await db.execute(
        select(func.coalesce(func.avg(Integration.sync_health), 0)).where(
            Integration.org_id == org.id,
            Integration.status == "connected",
        )
    )
    sync_health = int(sync_health_result.scalar() or 0)

    integrations_result = await db.execute(
        select(Integration).where(Integration.org_id == org.id)
    )
    integrations = [IntegrationResponse.model_validate(i) for i in integrations_result.scalars().all()]

    return IntegrationListResponse(
        connected=connected,
        pending=pending,
        sync_health=sync_health,
        integrations=integrations,
    )


@router.get("/available", response_model=list[AvailableIntegrationResponse])
async def list_available_integrations() -> list[AvailableIntegrationResponse]:
    """Return the full catalogue of supported integration providers.

    Tags (e.g. 'Popular', 'New', 'Indian Market') are metadata-only labels
    defined in AVAILABLE_PROVIDERS and never stored in the database.
    """
    return [
        AvailableIntegrationResponse(
            provider=provider,
            display_name=meta["display_name"],
            description=meta.get("description"),
            category=meta.get("category"),
            tags=meta.get("tags", []),
        )
        for provider, meta in AVAILABLE_PROVIDERS.items()
    ]


@router.get("/callback")
async def oauth_callback(
    entity_id: str | None = None,
    connection_id: str | None = None,
    connected_account_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Callback from Composio after successful OAuth authorization."""
    from app.config import get_settings
    settings = get_settings()
    frontend_url = settings.frontend_url or "http://localhost:5173"
    
    conn_id = connection_id or connected_account_id
    if not conn_id:
        return RedirectResponse(url=f"{frontend_url}/dashboard/integrations?error=missing_connection_id")

    # Resolve connection details directly from Composio API
    conn_info = await composio_gateway.get_connection_info(conn_id)
    if not conn_info:
        return RedirectResponse(url=f"{frontend_url}/dashboard/integrations?error=connection_not_found")

    resolved_entity_id = entity_id or conn_info.get("entity_id")
    if not resolved_entity_id:
        return RedirectResponse(url=f"{frontend_url}/dashboard/integrations?error=missing_entity_id")

    try:
        org_uuid = UUID(resolved_entity_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entity_id format")

    tool_name = conn_info.get("tool_name", "").upper()
    if not tool_name:
        return RedirectResponse(url=f"{frontend_url}/dashboard/integrations?error=unknown_tool")

    # Find the integration record in our DB
    result = await db.execute(
        select(Integration).where(
            Integration.org_id == org_uuid,
            Integration.provider == tool_name,
        )
    )
    integration = result.scalar_one_or_none()
    
    if not integration:
        meta = AVAILABLE_PROVIDERS.get(tool_name, {"display_name": tool_name.capitalize(), "description": "", "category": "Other"})
        integration = Integration(
            org_id=org_uuid,
            provider=tool_name,
            display_name=meta["display_name"],
            description=meta.get("description"),
            category=meta.get("category"),
        )
        db.add(integration)
        
    integration.status = "connected"
    integration.composio_connection_id = conn_id
    integration.sync_health = 100
    integration.last_synced = datetime.now(timezone.utc)
    
    await db.commit()
    
    return RedirectResponse(url=f"{frontend_url}/dashboard/integrations?success=true&provider={tool_name}")


@router.post("/initialize", response_model=IntegrationResponse)
async def initialize_integration(
    body: IntegrationInitializeRequest,
    org: Organization = Depends(get_current_org),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> IntegrationResponse:
    if body.provider not in AVAILABLE_PROVIDERS:
        raise HTTPException(status_code=400, detail="Unsupported integration provider")

    result = await db.execute(
        select(Integration).where(
            Integration.org_id == org.id,
            Integration.provider == body.provider,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return IntegrationResponse.model_validate(existing)

    meta = AVAILABLE_PROVIDERS[body.provider]
    integration = Integration(
        org_id=org.id,
        provider=body.provider,
        display_name=meta["display_name"],
        description=meta.get("description"),
        category=meta.get("category"),
        status="pending",
    )
    db.add(integration)
    await db.commit()
    await db.refresh(integration)
    return IntegrationResponse.model_validate(integration)


@router.post("/{integration_id}/connect")

async def connect_integration(
    integration_id: UUID,
    body: IntegrationConnectRequest,
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    result = await db.execute(
        select(Integration).where(
            Integration.id == integration_id,
            Integration.org_id == org.id,
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    from app.services.mcp.composio_gateway import COMPOSIO_TOOLS
    if integration.provider.upper() in COMPOSIO_TOOLS:
        redirect_url = await composio_gateway.connect_tool(
            org_id=str(org.id),
            tool_name=integration.provider,
            user_id=str(user.id),
        )
        if redirect_url:
            return {"redirect_url": redirect_url}
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to initiate connection for {integration.provider}. Please make sure COMPOSIO_API_KEY is configured in your .env file."
            )

    if integration.provider in ["TALLY", "GSTN"]:
        is_reachable = await check_tool_connectivity(integration.provider, org_id=str(org.id))
        if not is_reachable:
            raise HTTPException(
                status_code=400,
                detail=f"Could not connect to {integration.provider} server. Please ensure the native agent is running."
            )

    integration.status = "connected"
    integration.credentials_enc = encrypt(json.dumps(body.config))
    integration.sync_health = 100
    integration.last_synced = datetime.now(timezone.utc)




    await log_action(db, org_id=org.id, user_id=user.id,
                     action="integration_connected",
                     metadata={"integration_id": str(integration_id)})
    await db.commit()
    return IntegrationResponse.model_validate(integration)


@router.post("/{integration_id}/disconnect")
async def disconnect_integration(
    integration_id: UUID,
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> IntegrationResponse:
    result = await db.execute(
        select(Integration).where(
            Integration.id == integration_id,
            Integration.org_id == org.id,
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    if integration.status != "connected":
        raise HTTPException(status_code=400, detail="Integration is not connected")

    if integration.composio_connection_id:
        from app.services.mcp.composio_gateway import COMPOSIO_TOOLS
        if integration.provider.upper() in COMPOSIO_TOOLS:
            disconnected = await composio_gateway.disconnect_connection(integration.composio_connection_id)
            if not disconnected:
                raise HTTPException(status_code=502, detail="Failed to disconnect integration provider")

    integration.status = "disconnected"
    integration.credentials_enc = None
    integration.sync_health = 0
    integration.composio_connection_id = None
    integration.last_synced = None

    disconnect_alert = Alert(
        org_id=org.id,
        rule_id="INTEGRATION_DISCONNECTED",
        severity="warning",
        message=f"Integration '{integration.display_name}' was disconnected.",
    )
    db.add(disconnect_alert)

    await log_action(db, org_id=org.id, user_id=user.id,
                     action="integration_disconnected",
                     metadata={"integration_id": str(integration_id)})
    await db.commit()
    return IntegrationResponse.model_validate(integration)
