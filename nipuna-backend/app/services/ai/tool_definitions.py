"""AI Tool Definitions for LLM Function Calling.

Maps OpenAI-compatible tool call schemas to backend MCP actions.
"""

GMAIL_TOOLS = [
    {
        "name": "gmail_send_email",
        "description": "Send an email via Gmail",
        "parameters": {
            "type": "object",
            "properties": {
                "recipient": {"type": "string", "description": "Email address of the recipient"},
                "subject": {"type": "string", "description": "Subject of the email"},
                "body": {"type": "string", "description": "HTML or plain text body of the email"}
            },
            "required": ["recipient", "subject", "body"]
        },
        "provider": "GMAIL",
        "action": "GMAIL_SEND_EMAIL"
    },
    {
        "name": "gmail_search_emails",
        "description": "Search user's emails in Gmail",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query like 'from:boss' or 'invoice'"}
            },
            "required": ["query"]
        },
        "provider": "GMAIL",
        "action": "GMAIL_SEARCH_EMAILS"
    },
    {
        "name": "gmail_get_email",
        "description": "Get detailed content of a specific email",
        "parameters": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "The unique ID of the email message"}
            },
            "required": ["message_id"]
        },
        "provider": "GMAIL",
        "action": "GMAIL_GET_EMAIL"
    },
    {
        "name": "gmail_create_draft",
        "description": "Create a new draft in Gmail",
        "parameters": {
            "type": "object",
            "properties": {
                "recipient": {"type": "string", "description": "Email address of the recipient"},
                "subject": {"type": "string", "description": "Subject of the draft"},
                "body": {"type": "string", "description": "Body of the draft"}
            },
            "required": ["recipient", "subject", "body"]
        },
        "provider": "GMAIL",
        "action": "GMAIL_CREATE_DRAFT"
    }
]

SLACK_TOOLS = [
    {
        "name": "slack_send_message",
        "description": "Post a message to a Slack channel",
        "parameters": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "The channel name or ID (e.g. 'general')"},
                "text": {"type": "string", "description": "The message text to post"}
            },
            "required": ["channel", "text"]
        },
        "provider": "SLACK",
        "action": "SLACK_POST_MESSAGE"
    },
    {
        "name": "slack_list_channels",
        "description": "List all public channels in the Slack workspace",
        "parameters": {
            "type": "object",
            "properties": {}
        },
        "provider": "SLACK",
        "action": "SLACK_LIST_CHANNELS"
    }
]

GITHUB_TOOLS = [
    {
        "name": "github_create_issue",
        "description": "Create an issue in a GitHub repository",
        "parameters": {
            "type": "object",
            "properties": {
                "owner": {"type": "string", "description": "Owner/org of the repository"},
                "repo": {"type": "string", "description": "Repository name"},
                "title": {"type": "string", "description": "Title of the issue"},
                "body": {"type": "string", "description": "Description body of the issue"}
            },
            "required": ["owner", "repo", "title"]
        },
        "provider": "GITHUB",
        "action": "GITHUB_CREATE_ISSUE"
    },
    {
        "name": "github_list_issues",
        "description": "List issues in a GitHub repository",
        "parameters": {
            "type": "object",
            "properties": {
                "owner": {"type": "string", "description": "Owner/org of the repository"},
                "repo": {"type": "string", "description": "Repository name"},
                "state": {"type": "string", "enum": ["open", "closed", "all"], "default": "open"}
            },
            "required": ["owner", "repo"]
        },
        "provider": "GITHUB",
        "action": "GITHUB_LIST_ISSUES"
    }
]

JIRA_TOOLS = [
    {
        "name": "jira_create_issue",
        "description": "Create an issue in Jira",
        "parameters": {
            "type": "object",
            "properties": {
                "project_key": {"type": "string", "description": "Jira Project Key (e.g. 'PROJ')"},
                "summary": {"type": "string", "description": "Summary/title of the issue"},
                "description": {"type": "string", "description": "Description of the issue"},
                "issue_type": {"type": "string", "description": "Issue type (e.g. 'Bug', 'Task')", "default": "Task"}
            },
            "required": ["project_key", "summary"]
        },
        "provider": "JIRA",
        "action": "JIRA_CREATE_ISSUE"
    }
]

NOTION_TOOLS = [
    {
        "name": "notion_search_pages",
        "description": "Search pages or databases in Notion",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text query to search for"}
            },
            "required": ["query"]
        },
        "provider": "NOTION",
        "action": "NOTION_SEARCH"
    }
]

TALLY_TOOLS = [
    {
        "name": "tally_query_database",
        "description": "Query cached Tally report data using SQL (DuckDB)",
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SQL query to execute on cached report tables"}
            },
            "required": ["sql"]
        },
        "provider": "TALLY",
        "action": "query-database"
    },
    {
        "name": "tally_list_master",
        "description": "Fetch list of masters (group, ledger, vouchertype, unit, godown, stockgroup, stockitem, costcategory, costcentre, attendancetype, company, currency, gstin, gstclassification)",
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
        },
        "provider": "TALLY",
        "action": "list-master"
    },
    {
        "name": "tally_chart_of_accounts",
        "description": "Fetch chart of accounts / group structure",
        "parameters": {
            "type": "object",
            "properties": {}
        },
        "provider": "TALLY",
        "action": "chart-of-accounts"
    },
    {
        "name": "tally_trial_balance",
        "description": "Fetch trial balance for a date range",
        "parameters": {
            "type": "object",
            "properties": {
                "targetCompany": {"type": "string", "description": "Optional company name"},
                "fromDate": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                "toDate": {"type": "string", "description": "End date (YYYY-MM-DD)"}
            },
            "required": ["fromDate", "toDate"]
        },
        "provider": "TALLY",
        "action": "trial-balance"
    },
    {
        "name": "tally_profit_loss",
        "description": "Fetch profit and loss statement for a date range",
        "parameters": {
            "type": "object",
            "properties": {
                "targetCompany": {"type": "string", "description": "Optional company name"},
                "fromDate": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                "toDate": {"type": "string", "description": "End date (YYYY-MM-DD)"}
            },
            "required": ["fromDate", "toDate"]
        },
        "provider": "TALLY",
        "action": "profit-loss"
    },
    {
        "name": "tally_balance_sheet",
        "description": "Fetch balance sheet as of a date",
        "parameters": {
            "type": "object",
            "properties": {
                "targetCompany": {"type": "string", "description": "Optional company name"},
                "toDate": {"type": "string", "description": "As-of date (YYYY-MM-DD)"}
            },
            "required": ["toDate"]
        },
        "provider": "TALLY",
        "action": "balance-sheet"
    },
    {
        "name": "tally_stock_summary",
        "description": "Fetch stock item summary for a date range",
        "parameters": {
            "type": "object",
            "properties": {
                "targetCompany": {"type": "string", "description": "Optional company name"},
                "fromDate": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                "toDate": {"type": "string", "description": "End date (YYYY-MM-DD)"}
            },
            "required": ["fromDate", "toDate"]
        },
        "provider": "TALLY",
        "action": "stock-summary"
    },
    {
        "name": "tally_ledger_balance",
        "description": "Fetch ledger closing balance as of a date",
        "parameters": {
            "type": "object",
            "properties": {
                "targetCompany": {"type": "string", "description": "Optional company name"},
                "ledgerName": {"type": "string", "description": "Exact ledger name"},
                "toDate": {"type": "string", "description": "As-of date (YYYY-MM-DD)"}
            },
            "required": ["ledgerName", "toDate"]
        },
        "provider": "TALLY",
        "action": "ledger-balance"
    },
    {
        "name": "tally_stock_item_balance",
        "description": "Fetch stock item remaining quantity balance as of a date",
        "parameters": {
            "type": "object",
            "properties": {
                "targetCompany": {"type": "string", "description": "Optional company name"},
                "itemName": {"type": "string", "description": "Exact stock item name"},
                "toDate": {"type": "string", "description": "As-of date (YYYY-MM-DD)"}
            },
            "required": ["itemName", "toDate"]
        },
        "provider": "TALLY",
        "action": "stock-item-balance"
    },
    {
        "name": "tally_bills_outstanding",
        "description": "Fetch outstanding receivables/payables as of a date",
        "parameters": {
            "type": "object",
            "properties": {
                "targetCompany": {"type": "string", "description": "Optional company name"},
                "nature": {"type": "string", "enum": ["receivable", "payable"]},
                "toDate": {"type": "string", "description": "As-of date (YYYY-MM-DD)"}
            },
            "required": ["nature", "toDate"]
        },
        "provider": "TALLY",
        "action": "bills-outstanding"
    },
    {
        "name": "tally_ledger_account",
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
        },
        "provider": "TALLY",
        "action": "ledger-account"
    },
    {
        "name": "tally_stock_item_account",
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
        },
        "provider": "TALLY",
        "action": "stock-item-account"
    }
]

GSTN_TOOLS = [
    {
        "name": "gstn_get_gst_returns",
        "description": "Fetch GST returns for a GSTIN and period",
        "parameters": {
            "type": "object",
            "properties": {
                "gstin": {"type": "string", "description": "15-character GSTIN"},
                "period": {"type": "string", "description": "Tax period (MMYYYY)"}
            },
            "required": ["gstin", "period"]
        },
        "provider": "GSTN",
        "action": "get_gst_returns"
    },
    {
        "name": "gstn_verify_gstin",
        "description": "Verify a GSTIN number and return registration details",
        "parameters": {
            "type": "object",
            "properties": {
                "gstin": {"type": "string", "description": "15-character GSTIN"}
            },
            "required": ["gstin"]
        },
        "provider": "GSTN",
        "action": "verify_gstin"
    },
    {
        "name": "gstn_get_taxpayer_details",
        "description": "Get detailed taxpayer information for a GSTIN",
        "parameters": {
            "type": "object",
            "properties": {
                "gstin": {"type": "string", "description": "15-character GSTIN"}
            },
            "required": ["gstin"]
        },
        "provider": "GSTN",
        "action": "get_taxpayer_details"
    }
]

PROVIDER_TOOLS_MAPPING = {
    "GMAIL": GMAIL_TOOLS,
    "SLACK": SLACK_TOOLS,
    "GITHUB": GITHUB_TOOLS,
    "JIRA": JIRA_TOOLS,
    "NOTION": NOTION_TOOLS,
    "TALLY": TALLY_TOOLS,
    "GSTN": GSTN_TOOLS,
}


def get_tools_for_providers(providers: list[str]) -> list[dict]:
    """Compile function schemas for a list of active providers."""
    tools = []
    for provider in providers:
        p_upper = provider.upper()
        if p_upper in PROVIDER_TOOLS_MAPPING:
            tools.extend(PROVIDER_TOOLS_MAPPING[p_upper])
    return tools


def map_tool_to_action(tool_name: str) -> tuple[str, str] | None:
    """Map LLM tool call name to (provider, action_name)."""
    for provider, tools in PROVIDER_TOOLS_MAPPING.items():
        for tool in tools:
            if tool["name"] == tool_name:
                return tool["provider"], tool["action"]
    return None
