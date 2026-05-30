from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from app.services.mcp.composio_gateway import COMPOSIO_TOOLS, ComposioGateway, composio_gateway

COMPOSIO_TOOLS_LIST = COMPOSIO_TOOLS

AVAILABLE_PROVIDERS = {
    "SLACK": {"display_name": "Slack", "description": "Connect your workspace for real-time notifications and collaboration.", "category": "Marketing"},
    "GMAIL": {"display_name": "Gmail", "description": "Sync your emails and automate communication flows.", "category": "Marketing"},
    "GITHUB": {"display_name": "GitHub", "description": "Manage repositories, issues, and pull requests directly.", "category": "Database"},
    "JIRA": {"display_name": "Jira", "description": "Track tasks, bugs, and project progress.", "category": "Product Analytics"},
    "NOTION": {"display_name": "Notion", "description": "Sync your knowledge base and documents.", "category": "Product Analytics"},
    "SALESFORCE": {"display_name": "Salesforce", "description": "Manage your CRM and customer pipelines.", "category": "Product Analytics"},
    "HUBSPOT": {"display_name": "HubSpot", "description": "Integrate your marketing and sales hub.", "category": "Marketing"},
    "ASANA": {"display_name": "Asana", "description": "Organize your work and track team progress.", "category": "Product Analytics"},
    "TRELLO": {"display_name": "Trello", "description": "Manage your boards and cards.", "category": "Product Analytics"},
    "ZENDESK": {"display_name": "Zendesk", "description": "Streamline your customer support tickets.", "category": "Marketing"},
    "WHATSAPP": {"display_name": "WhatsApp", "description": "Send notifications and interact with customers.", "category": "Marketing"},
    "GOOGLE_CALENDAR": {"display_name": "Google Calendar", "description": "Schedule events and manage your calendar.", "category": "Product Analytics"},
    "MICROSOFT_TEAMS": {"display_name": "Microsoft Teams", "description": "Send channel alerts and collaborate with teams.", "category": "Marketing"},
    "TALLY": {"display_name": "Tally", "description": "Connect your Tally accounting data.", "category": "Desktop tools"},
    "GSTN": {"display_name": "GSTN", "description": "Access government tax filings and data.", "category": "Warehouse & Data Lakes"},
}


async def execute_tool(
    org_id: str,
    tool_name: str,
    action: str,
    params: dict,
) -> dict:
    if tool_name.upper() in COMPOSIO_TOOLS:
        return await composio_gateway.execute_action(org_id, tool_name, action, params)

    from app.services.mcp.native.tally_server import execute_tally_action
    from app.services.mcp.native.gstn_server import execute_gstn_action

    if tool_name.upper() == "TALLY":
        return await execute_tally_action(action, params, org_id)
    if tool_name.upper() == "GSTN":
        return await execute_gstn_action(action, params)

    return {"error": f"Unknown tool: {tool_name}"}


async def check_tool_connectivity(tool_name: str, org_id: str | None = None) -> bool:
    """Checks if a native tool is actually reachable."""
    if tool_name.upper() == "TALLY":
        from app.services.mcp.agent_hub import agent_hub

        resolved_org_id = UUID(org_id) if org_id else None
        return agent_hub.has_capability(org_id=resolved_org_id, capability="tally")

    if tool_name.upper() == "GSTN":
        # GSTN is an external API; we check if the API key is configured
        from app.config import get_settings
        settings = get_settings()
        return hasattr(settings, "gstn_api_key") and bool(settings.gstn_api_key)

    return False


async def get_available_tools_for_org(org_id: str, db: AsyncSession) -> dict[str, list[dict]]:
    """Get all connected tools and their available actions/definitions for an org."""
    from sqlalchemy import select
    from app.models.integration import Integration

    result = await db.execute(
        select(Integration).where(
            Integration.org_id == org_id,
            Integration.status == "connected",
        )
    )
    connected = result.scalars().all()
    
    tools: dict[str, list[dict]] = {}
    for integration in connected:
        provider = integration.provider.upper()
        if provider in COMPOSIO_TOOLS:
            actions = await composio_gateway.get_available_actions(provider)
            if actions:
                tools[provider] = actions
        elif provider == "TALLY":
            # Native Tally definitions
            tools["TALLY"] = [
                {
                    "name": "query-database",
                    "display_name": "Query Database",
                    "description": "Execute SQL query on cached Tally report data",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sql": {"type": "string", "description": "SQL query to execute"}
                        },
                        "required": ["sql"]
                    }
                },
                {
                    "name": "list-master",
                    "display_name": "List Masters",
                    "description": "Fetch list of masters for validation and selection",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "targetCompany": {"type": "string", "description": "Optional company name"},
                            "collection": {
                                "type": "string",
                                "enum": [
                                    "group",
                                    "ledger",
                                    "vouchertype",
                                    "unit",
                                    "godown",
                                    "stockgroup",
                                    "stockitem",
                                    "costcategory",
                                    "costcentre",
                                    "attendancetype",
                                    "company",
                                    "currency",
                                    "gstin",
                                    "gstclassification"
                                ]
                            }
                        },
                        "required": ["collection"]
                    }
                },
                {
                    "name": "chart-of-accounts",
                    "display_name": "Chart of Accounts",
                    "description": "Fetch chart of accounts / group hierarchy",
                    "parameters": {
                        "type": "object",
                        "properties": {}
                    }
                },
                {
                    "name": "trial-balance",
                    "display_name": "Trial Balance",
                    "description": "Fetch trial balance for a date range",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "targetCompany": {"type": "string", "description": "Optional company name"},
                            "fromDate": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                            "toDate": {"type": "string", "description": "End date (YYYY-MM-DD)"}
                        },
                        "required": ["fromDate", "toDate"]
                    }
                },
                {
                    "name": "profit-loss",
                    "display_name": "Profit and Loss",
                    "description": "Fetch profit and loss statement for a date range",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "targetCompany": {"type": "string", "description": "Optional company name"},
                            "fromDate": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                            "toDate": {"type": "string", "description": "End date (YYYY-MM-DD)"}
                        },
                        "required": ["fromDate", "toDate"]
                    }
                },
                {
                    "name": "balance-sheet",
                    "display_name": "Balance Sheet",
                    "description": "Fetch balance sheet as of a date",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "targetCompany": {"type": "string", "description": "Optional company name"},
                            "toDate": {"type": "string", "description": "As-of date (YYYY-MM-DD)"}
                        },
                        "required": ["toDate"]
                    }
                },
                {
                    "name": "stock-summary",
                    "display_name": "Stock Summary",
                    "description": "Fetch stock summary for a date range",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "targetCompany": {"type": "string", "description": "Optional company name"},
                            "fromDate": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                            "toDate": {"type": "string", "description": "End date (YYYY-MM-DD)"}
                        },
                        "required": ["fromDate", "toDate"]
                    }
                },
                {
                    "name": "ledger-balance",
                    "display_name": "Ledger Balance",
                    "description": "Fetch ledger closing balance as of a date",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "targetCompany": {"type": "string", "description": "Optional company name"},
                            "ledgerName": {"type": "string", "description": "Exact ledger name"},
                            "toDate": {"type": "string", "description": "As-of date (YYYY-MM-DD)"}
                        },
                        "required": ["ledgerName", "toDate"]
                    }
                },
                {
                    "name": "stock-item-balance",
                    "display_name": "Stock Item Balance",
                    "description": "Fetch stock item closing quantity as of a date",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "targetCompany": {"type": "string", "description": "Optional company name"},
                            "itemName": {"type": "string", "description": "Exact stock item name"},
                            "toDate": {"type": "string", "description": "As-of date (YYYY-MM-DD)"}
                        },
                        "required": ["itemName", "toDate"]
                    }
                },
                {
                    "name": "bills-outstanding",
                    "display_name": "Bills Outstanding",
                    "description": "Fetch outstanding receivables/payables as of a date",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "targetCompany": {"type": "string", "description": "Optional company name"},
                            "nature": {"type": "string", "enum": ["receivable", "payable"]},
                            "toDate": {"type": "string", "description": "As-of date (YYYY-MM-DD)"}
                        },
                        "required": ["nature", "toDate"]
                    }
                },
                {
                    "name": "ledger-account",
                    "display_name": "Ledger Account",
                    "description": "Fetch ledger account statement for a date range",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "targetCompany": {"type": "string", "description": "Optional company name"},
                            "ledgerName": {"type": "string", "description": "Exact ledger name"},
                            "fromDate": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                            "toDate": {"type": "string", "description": "End date (YYYY-MM-DD)"}
                        },
                        "required": ["ledgerName", "fromDate", "toDate"]
                    }
                },
                {
                    "name": "stock-item-account",
                    "display_name": "Stock Item Account",
                    "description": "Fetch stock item account statement for a date range",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "targetCompany": {"type": "string", "description": "Optional company name"},
                            "itemName": {"type": "string", "description": "Exact stock item name"},
                            "fromDate": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                            "toDate": {"type": "string", "description": "End date (YYYY-MM-DD)"}
                        },
                        "required": ["itemName", "fromDate", "toDate"]
                    }
                }
            ]
        elif provider == "GSTN":
            # Native GSTN definitions
            tools["GSTN"] = [
                {
                    "name": "get_gst_returns",
                    "display_name": "Get GST Returns",
                    "description": "Fetch GST returns for a GSTIN and filing period",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "gstin": {"type": "string", "description": "15-character GSTIN"},
                            "period": {"type": "string", "description": "Tax period (MMYYYY)"}
                        },
                        "required": ["gstin", "period"]
                    }
                },
                {
                    "name": "verify_gstin",
                    "display_name": "Verify GSTIN",
                    "description": "Verify a GSTIN number and return registration details",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "gstin": {"type": "string", "description": "15-character GSTIN"}
                        },
                        "required": ["gstin"]
                    }
                },
                {
                    "name": "get_taxpayer_details",
                    "display_name": "Get Taxpayer Details",
                    "description": "Get detailed taxpayer information for a GSTIN",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "gstin": {"type": "string", "description": "15-character GSTIN"}
                        },
                        "required": ["gstin"]
                    }
                }
            ]
    return tools
