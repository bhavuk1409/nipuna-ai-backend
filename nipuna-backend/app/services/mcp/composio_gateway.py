"""Composio SDK gateway for third-party tool integrations.

Uses Composio from the new composio SDK to manage OAuth connections
and execute actions on connected tools like Gmail, Slack, GitHub, etc.
"""

import logging
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

COMPOSIO_TOOLS = [
    "SLACK", "GMAIL", "GITHUB", "JIRA", "NOTION",
    "SALESFORCE", "HUBSPOT", "ASANA", "TRELLO", "ZENDESK",
    "GOOGLE_CALENDAR", "MICROSOFT_TEAMS", "WHATSAPP",
]

SLUG_MAPPINGS = {
    "GOOGLE_CALENDAR": "googlecalendar",
}



class ComposioGateway:
    """Gateway to the Composio managed integration platform.

    Handles OAuth connection initiation, action execution, and connection
    management for all Composio-supported tools. Gracefully degrades
    when COMPOSIO_API_KEY is not configured.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._toolset: Any | None = None

    @property
    def _is_configured(self) -> bool:
        return bool(self._settings.composio_api_key)

    def _get_toolset(self) -> Any:
        """Lazily initialize the Composio client."""
        if self._toolset is None:
            try:
                from composio import Composio
                self._toolset = Composio(api_key=self._settings.composio_api_key)
            except ImportError:
                logger.error("composio package is not installed. Run: pip install composio")
                raise
        return self._toolset

    async def connect_tool(
        self,
        org_id: str,
        tool_name: str,
        user_id: str,
        redirect_url: str | None = None,
    ) -> str:
        """Initiate an OAuth connection for a tool.

        Returns the OAuth redirect URL the user should be sent to,
        or an empty string if Composio is not configured.
        """
        if not self._is_configured:
            logger.warning("Composio not configured — cannot connect tool %s", tool_name)
            return ""

        try:
            client = self._get_toolset()

            # Build the redirect URL for the OAuth callback
            if not redirect_url:
                settings = self._settings
                base = getattr(settings, "composio_redirect_url", None)
                if not base:
                    base = "http://localhost:8000/api/v1/integrations/callback"
                sep = "&" if "?" in base else "?"
                redirect_url = f"{base}{sep}entity_id={org_id}"

            # 1. List auth configs to find the matching toolkit slug
            auth_configs = client.auth_configs.list()
            target_config = None
            toolkit_slug = SLUG_MAPPINGS.get(tool_name.upper(), tool_name.lower())
            for config in auth_configs.items:
                if config.toolkit and config.toolkit.slug.lower() == toolkit_slug.lower():
                    target_config = config
                    break

            if not target_config:
                # If not found, try to create a default one
                try:
                    target_config = client.auth_configs.create(
                        toolkit=toolkit_slug,
                        options={"type": "use_composio_managed_auth"}
                    )
                except Exception as exc:
                    logger.error("Failed to create auth config for %s: %s", tool_name, exc)
                    return ""

            auth_config_id = target_config.id

            # 2. Initiate link via new v3 SDK method
            connection_request = client.connected_accounts.link(
                user_id=org_id,
                auth_config_id=auth_config_id,
                callback_url=redirect_url,
                allow_multiple=True,
            )

            url = getattr(connection_request, "redirect_url", "")
            logger.info(
                "Composio OAuth initiated for tool=%s org=%s → redirect=%s",
                tool_name, org_id, url[:80] if url else "(none)",
            )
            return url or ""

        except Exception as exc:
            logger.error("Composio connect_tool failed for %s: %s", tool_name, exc, exc_info=True)
            return ""

    async def execute_action(
        self,
        org_id: str,
        tool_name: str,
        action: str,
        params: dict,
    ) -> dict:
        """Execute an action on a connected tool.

        Args:
            org_id: The organization entity ID.
            tool_name: Tool name (e.g., 'GMAIL').
            action: Action identifier (e.g., 'GMAIL_SEND_EMAIL').
            params: Parameters for the action.

        Returns:
            Result dict with either 'result' or 'error' key.
        """
        if not self._is_configured:
            return {"error": "Composio not configured"}

        try:
            client = self._get_toolset()

            # The action slug comes from the Composio tools.get() response (e.g. "GMAIL_FETCH_EMAILS").
            # Composio API v2 accepts the slug in the same form it returns it — do NOT transform case.
            # Previous lowercasing (action.lower()) caused 404 "Tool not found" errors.
            result = client.tools.execute(
                slug=action,
                arguments=params,
                user_id=org_id,
                dangerously_skip_version_check=True,
            )

            # Support both object and dict representation of ToolExecutionResponse
            successful = getattr(result, "successful", None)
            if successful is None and isinstance(result, dict):
                successful = result.get("successful")

            data = getattr(result, "data", None)
            if data is None and isinstance(result, dict):
                data = result.get("data")

            error = getattr(result, "error", None)
            if error is None and isinstance(result, dict):
                error = result.get("error")

            if successful:
                return {"tool_name": tool_name, "result": data, "error": None}
            return {"tool_name": tool_name, "result": None, "error": error}

        except Exception as exc:
            logger.error(
                "Composio execute_action failed: tool=%s action=%s error=%s",
                tool_name, action, exc,
                exc_info=True,
            )
            return {"tool_name": tool_name, "result": None, "error": str(exc)}

    async def list_connections(self, org_id: str) -> list[dict]:
        """List all active connections for an organization."""
        if not self._is_configured:
            return []

        try:
            client = self._get_toolset()
            connections = client.connected_accounts.list(user_ids=[org_id])

            return [
                {
                    "tool_name": item.toolkit.slug.upper() if item.toolkit else "UNKNOWN",
                    "status": item.status.upper(),
                    "connected_at": item.created_at,
                    "connection_id": item.id,
                }
                for item in connections.items
            ]
        except Exception as exc:
            logger.error("Composio list_connections failed: %s", exc, exc_info=True)
            return []

    async def disconnect_connection(self, connection_id: str) -> bool:
        """Disconnect a Composio connection by ID."""
        if not self._is_configured:
            return False

        try:
            client = self._get_toolset()
            client.connected_accounts.delete(connection_id)
            return True
        except Exception as exc:
            logger.error("Composio disconnect_connection failed for %s: %s", connection_id, exc, exc_info=True)
            return False

    async def get_connection_info(self, connection_id: str) -> dict | None:
        """Fetch connection details from Composio by connection ID."""
        if not self._is_configured:
            return None
        try:
            # Under the hood client.connected_accounts.get requires blocking call
            # using standard client resources
            client = self._get_toolset()
            item = client.connected_accounts.get(connection_id)
            return {
                "connection_id": item.id,
                "tool_name": item.toolkit.slug.upper() if item.toolkit else "UNKNOWN",
                "entity_id": item.user_id,
                "status": item.status.upper(),
            }
        except Exception as exc:
            logger.error("Composio get_connection_info failed for %s: %s", connection_id, exc)
            return None

    async def get_available_actions(self, tool_name: str) -> list[dict]:
        """Get the list of available actions for a given tool."""
        if not self._is_configured:
            return []

        try:
            client = self._get_toolset()
            toolkit_slug = SLUG_MAPPINGS.get(tool_name.upper(), tool_name.lower())
            actions = client.tools.get(user_id="dummy", toolkits=[toolkit_slug])

            return [
                {
                    "name": a["function"]["name"],
                    "display_name": a["function"]["name"],
                    "description": a["function"]["description"],
                    "parameters": a["function"]["parameters"],
                }
                for a in actions
                if "function" in a
            ]
        except Exception as exc:
            logger.error("Composio get_available_actions failed for %s: %s", tool_name, exc)
            return []

    async def get_tools_for_entity(self, org_id: str) -> dict[str, list[dict]]:
        """Get all connected tools and their available actions for an org."""
        if not self._is_configured:
            return {}

        connections = await self.list_connections(org_id)
        tools: dict[str, list[dict]] = {}

        for conn in connections:
            tool_name = conn.get("tool_name", "")
            if not tool_name or conn.get("status") != "ACTIVE":
                continue
            actions = await self.get_available_actions(tool_name)
            if actions:
                tools[tool_name] = actions

        return tools


# Singleton instance — import from here
composio_gateway = ComposioGateway()
