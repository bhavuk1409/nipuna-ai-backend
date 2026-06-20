from typing import TypedDict
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from app.services.mcp.composio_gateway import COMPOSIO_TOOLS, ComposioGateway, composio_gateway  # noqa: F401

COMPOSIO_TOOLS_LIST = COMPOSIO_TOOLS


class ProviderMeta(TypedDict, total=False):
    display_name: str
    description: str
    category: str
    tags: list[str]


AVAILABLE_PROVIDERS: dict[str, ProviderMeta] = {
    # ── Collaboration & Communication ────────────────────────────────────────
    "SLACK": {
        "display_name": "Slack",
        "description": "Connect your workspace for real-time notifications and AI-driven collaboration.",
        "category": "Collaboration",
        "tags": ["Popular"],
    },
    "GMAIL": {
        "display_name": "Gmail",
        "description": "Sync your emails and automate end-to-end communication flows.",
        "category": "Collaboration",
        "tags": ["Popular"],
    },
    "MICROSOFT_TEAMS": {
        "display_name": "Microsoft Teams",
        "description": "Send channel alerts and trigger workflows from team conversations.",
        "category": "Collaboration",
        "tags": [],
    },
    "DISCORD": {
        "display_name": "Discord",
        "description": "Post messages and react to events in your Discord servers.",
        "category": "Collaboration",
        "tags": ["New"],
    },
    "WHATSAPP": {
        "display_name": "WhatsApp",
        "description": "Send automated notifications and interact with customers over WhatsApp.",
        "category": "Collaboration",
        "tags": ["Popular", "Indian Market"],
    },
    # ── Project Management ───────────────────────────────────────────────────
    "GITHUB": {
        "display_name": "GitHub",
        "description": "Manage repositories, issues, and pull requests directly from Nipuna AI.",
        "category": "Developer Tools",
        "tags": ["Popular"],
    },
    "JIRA": {
        "display_name": "Jira",
        "description": "Track tasks, bugs, and project progress with full two-way sync.",
        "category": "Project Management",
        "tags": ["Popular"],
    },
    "ASANA": {
        "display_name": "Asana",
        "description": "Organise your work and keep your team on track with task automation.",
        "category": "Project Management",
        "tags": [],
    },
    "TRELLO": {
        "display_name": "Trello",
        "description": "Manage boards and cards; trigger actions from AI insights.",
        "category": "Project Management",
        "tags": [],
    },
    "LINEAR": {
        "display_name": "Linear",
        "description": "Streamline your engineering workflows with AI-powered issue management.",
        "category": "Developer Tools",
        "tags": ["New"],
    },
    # ── Knowledge & Productivity ─────────────────────────────────────────────
    "NOTION": {
        "display_name": "Notion",
        "description": "Sync your knowledge base and auto-generate pages from AI outputs.",
        "category": "Productivity",
        "tags": ["Popular"],
    },
    "GOOGLE_CALENDAR": {
        "display_name": "Google Calendar",
        "description": "Schedule events and let AI manage your calendar intelligently.",
        "category": "Productivity",
        "tags": ["Popular"],
    },
    "CALENDLY": {
        "display_name": "Calendly",
        "description": "Automate scheduling and meeting management with AI-driven availability.",
        "category": "Productivity",
        "tags": ["New"],
    },
    "AIRTABLE": {
        "display_name": "Airtable",
        "description": "Query and update your Airtable bases as a structured data source.",
        "category": "Database",
        "tags": ["New"],
    },
    # ── CRM & Marketing ──────────────────────────────────────────────────────
    "SALESFORCE": {
        "display_name": "Salesforce",
        "description": "Manage your CRM, customer pipelines, and revenue intelligence.",
        "category": "CRM & Marketing",
        "tags": ["Popular"],
    },
    "HUBSPOT": {
        "display_name": "HubSpot",
        "description": "Integrate your marketing, sales hub, and contact management.",
        "category": "CRM & Marketing",
        "tags": ["Popular"],
    },
    "ZENDESK": {
        "display_name": "Zendesk",
        "description": "Streamline customer support tickets and resolve queries with AI.",
        "category": "CRM & Marketing",
        "tags": [],
    },
    "INTERCOM": {
        "display_name": "Intercom",
        "description": "Automate customer messaging and support conversations at scale.",
        "category": "CRM & Marketing",
        "tags": ["New"],
    },
    "INSTAGRAM": {
        "display_name": "Instagram",
        "description": "Monitor brand mentions and automate Instagram business messaging.",
        "category": "CRM & Marketing",
        "tags": ["New"],
    },
    "TWITTER": {
        "display_name": "Twitter / X",
        "description": "Monitor brand mentions and automate posts and DMs.",
        "category": "CRM & Marketing",
        "tags": ["New"],
    },
    # ── Storage ──────────────────────────────────────────────────────────────
    "GOOGLEDRIVE": {
        "display_name": "Google Drive",
        "description": "Read, write, and index your Drive files as an AI knowledge source.",
        "category": "Storage",
        "tags": ["Popular"],
    },
    "DROPBOX": {
        "display_name": "Dropbox",
        "description": "Connect your Dropbox for document retrieval and AI-powered search.",
        "category": "Storage",
        "tags": ["New"],
    },
    # ── Finance & Payments ───────────────────────────────────────────────────
    "STRIPE": {
        "display_name": "Stripe",
        "description": "Access payment data, invoices, and subscription analytics.",
        "category": "Finance & Payments",
        "tags": ["Popular"],
    },
    "QUICKBOOKS": {
        "display_name": "QuickBooks",
        "description": "Sync accounting data, invoices, and financial reports automatically.",
        "category": "Finance & Payments",
        "tags": ["New"],
    },
    "XERO": {
        "display_name": "Xero",
        "description": "Connect your cloud accounting for automated bookkeeping insights.",
        "category": "Finance & Payments",
        "tags": ["New"],
    },
    "RAZORPAY": {
        "display_name": "Razorpay",
        "description": "Access your Indian payment gateway data, settlements, and analytics.",
        "category": "Finance & Payments",
        "tags": ["New", "Indian Market"],
    },
    # ── E-commerce ───────────────────────────────────────────────────────────
    "SHOPIFY": {
        "display_name": "Shopify",
        "description": "Sync orders, inventory, and customer data from your Shopify store.",
        "category": "E-commerce",
        "tags": ["New"],
    },
    # ── Video Conferencing ───────────────────────────────────────────────────
    "ZOOM": {
        "display_name": "Zoom",
        "description": "Schedule meetings and access transcripts from Zoom sessions.",
        "category": "Video Conferencing",
        "tags": ["New"],
    },
    # ── Native Integrations ──────────────────────────────────────────────────
    "TALLY": {
        "display_name": "Tally",
        "description": "Connect your on-premise Tally ERP 9 / Prime accounting data via a local desktop bridge.",
        "category": "Desktop Tools",
        "tags": ["Indian Market"],
    },
    "GSTN": {
        "display_name": "GSTN",
        "description": "Access government GST portal data — verify GSTINs and fetch filing history.",
        "category": "Warehouse & Data Lakes",
        "tags": ["Indian Market"],
    },
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


async def get_available_tools_for_org(org_id: str | UUID, db: AsyncSession) -> dict[str, list[dict]]:
    """Get all connected tools and their available actions/definitions for an org."""
    from sqlalchemy import select
    from app.models.integration import Integration
    from uuid import UUID as PyUUID

    resolved_org_id = PyUUID(org_id) if isinstance(org_id, str) else org_id

    result = await db.execute(
        select(Integration).where(
            Integration.org_id == resolved_org_id,
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
