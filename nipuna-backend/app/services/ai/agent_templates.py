"""Per-domain agent templates.

Templates own the *voice* of an agent — the system-prompt suffix that
differentiates a finance cashflow assistant from a sales/receivables
assistant from a general business assistant. The shared parts of the
prompt (RULES, NEVER list, VOICE & TONE header) live in
``langgraph_pipeline._SYSTEM_TEMPLATE``; the per-template suffix
appended to that template is defined here.

Templates are *not* a tool allowlist. The org's integrations remain
the source of truth for what's available; the template just
emphasises which kinds of integrations to prefer and which example
queries to surface in the empty state.

Ship 3 in v1: ``finance_cashflow``, ``sales_receivables``,
``general_assistant``. More to come after usage data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


TemplateId = Literal["finance_cashflow", "sales_receivables", "general_assistant"]


@dataclass(frozen=True)
class AgentTemplate:
    id: TemplateId
    name: str
    domain: str
    objective: str
    icon: str
    color: str
    system_prompt_suffix: str
    example_queries: tuple[str, ...]
    default_tone: str
    default_currency: str
    preferred_datasources: tuple[str, ...] = field(default_factory=tuple)


_FINANCE_TEMPLATE = AgentTemplate(
    id="finance_cashflow",
    name="Cashflow & Finance",
    domain="Finance, Cashflow, Treasury",
    objective=(
        "Help the user understand and act on the company's cash position, "
        "outstanding receivables / payables, and short-term forecasting. "
        "Always anchor numbers in tool results and cite the source."
    ),
    icon="TrendingUp",
    color="#16a34a",
    system_prompt_suffix=(
        "When the user asks about money, lead with the headline number "
        "(e.g. 'You have ₹18.4L in receivables, oldest is 47 days'). "
        "When a follow-up asks for a breakdown, give a short bulleted "
        "list. Use the user's preferred currency throughout."
    ),
    example_queries=(
        "What's our current cash position?",
        "Show me the top 5 outstanding receivables by amount.",
        "Which invoices are overdue by 60+ days?",
        "Compare this month's expenses to last month.",
        "Forecast cash for the next 30 days.",
        "What did we collect last week, and from whom?",
    ),
    default_tone="concise",
    default_currency="INR",
    preferred_datasources=("TALLY", "GSTN"),
)


_SALES_TEMPLATE = AgentTemplate(
    id="sales_receivables",
    name="Sales & Receivables",
    domain="Sales, Customers, Receivables",
    objective=(
        "Help the user track customer balances, outstanding invoices, "
        "and the sales pipeline. Surface the customers and invoices "
        "that most need attention today."
    ),
    icon="Users",
    color="#2563eb",
    system_prompt_suffix=(
        "When asked about customers or invoices, sort by what matters "
        "most (overdue first, then by amount). Always say which time "
        "window the data covers — sales answers without a date range "
        "are vague and unhelpful."
    ),
    example_queries=(
        "Who are my top 10 customers by revenue this quarter?",
        "Which customers have overdue invoices over ₹50k?",
        "Show me last week's new invoices.",
        "What's the average days-to-payment for Bluebell Traders?",
        "How many invoices did we raise this month vs last?",
        "Break down outstanding receivables by age bucket.",
    ),
    default_tone="concise",
    default_currency="INR",
    preferred_datasources=("TALLY",),
)


_GENERAL_TEMPLATE = AgentTemplate(
    id="general_assistant",
    name="Nipuna AI",
    domain="General Business",
    objective=(
        "Be a useful, specific assistant for the connected business. "
        "Anchor every claim in a tool result; ask one focused question "
        "when the request is ambiguous."
    ),
    icon="Sparkles",
    color="#7c3aed",
    system_prompt_suffix=(
        "Default voice: warm, specific, and concise. Use the user's "
        "preferred currency and tone. When the user greets you or asks "
        "what you can do, give a 2-3 line answer and offer 3 example "
        "questions you can answer for them right now."
    ),
    example_queries=(
        "Summarise this week's activity across our connected tools.",
        "What's overdue and needs my attention today?",
        "Help me draft a polite follow-up email to my slowest-paying customer.",
        "Show me the last 5 conversations we've had.",
        "Which integrations are connected and what can they do?",
        "What's the best question to ask you right now?",
    ),
    default_tone="professional",
    default_currency="INR",
    preferred_datasources=(),
)


AGENT_TEMPLATES: dict[str, AgentTemplate] = {
    "finance_cashflow": _FINANCE_TEMPLATE,
    "sales_receivables": _SALES_TEMPLATE,
    "general_assistant": _GENERAL_TEMPLATE,
}


DEFAULT_TEMPLATE_ID: TemplateId = "general_assistant"


def get_template(template_id: str | None) -> AgentTemplate:
    """Return a template by id, falling back to the default if id is unknown."""
    if not template_id:
        return AGENT_TEMPLATES[DEFAULT_TEMPLATE_ID]
    return AGENT_TEMPLATES.get(template_id, AGENT_TEMPLATES[DEFAULT_TEMPLATE_ID])


def list_templates() -> list[AgentTemplate]:
    """Return all templates in display order."""
    return [AGENT_TEMPLATES[DEFAULT_TEMPLATE_ID], _FINANCE_TEMPLATE, _SALES_TEMPLATE]


def is_valid_template_id(template_id: str | None) -> bool:
    return bool(template_id) and template_id in AGENT_TEMPLATES


__all__ = [
    "AGENT_TEMPLATES",
    "AgentTemplate",
    "DEFAULT_TEMPLATE_ID",
    "TemplateId",
    "get_template",
    "is_valid_template_id",
    "list_templates",
]
