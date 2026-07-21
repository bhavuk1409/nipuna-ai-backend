from fastapi import APIRouter

from app.routers import agents, auth, chat, dashboard, desktop, integrations, notifications, onboarding, settings, team, workflows
from app.routers.agent_socket import router as agent_socket_router
from app.routers import conversations as conversations_router
from app.routers import knowledge as knowledge_router
from app.routers import memories as memories_router

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(onboarding.router)
api_router.include_router(dashboard.router)
api_router.include_router(agents.router)
api_router.include_router(chat.router)
api_router.include_router(integrations.router)
# billing.router is disabled for now
# api_router.include_router(billing.router)
api_router.include_router(settings.router)
api_router.include_router(notifications.router)
api_router.include_router(team.router)
api_router.include_router(workflows.router)
# webhooks.router is disabled for now (handles Razorpay webhooks)
# api_router.include_router(webhooks.router)
api_router.include_router(agent_socket_router)
api_router.include_router(desktop.router)
api_router.include_router(conversations_router.router)
api_router.include_router(knowledge_router.router)
api_router.include_router(memories_router.router)

__all__ = ["api_router"]
