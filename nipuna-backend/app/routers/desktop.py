"""Desktop app authentication endpoints."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)

# API routes mounted under /api/v1/desktop
router = APIRouter(prefix="/desktop", tags=["desktop"])
# Page route mounted at root level
page_router = APIRouter(tags=["desktop"])

# In-memory store: opaque_token -> { clerk_jwt, expires_at, user_id }
_desktop_tokens: dict[str, dict[str, Any]] = {}

CLERK_PUBLISHABLE_KEY = "pk_test_ZWxlZ2FudC1sb2N1c3QtNC5jbGVyay5hY2NvdW50cy5kZXYk"
CLERK_DOMAIN = "elegant-locust-4.clerk.accounts.dev"

DESKTOP_AUTH_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Nipuna AI — Desktop Sign In</title>
  <script
    crossorigin="anonymous"
    data-clerk-publishable-key="{clerk_publishable_key}"
    src="https://{clerk_domain}/npm/@clerk/clerk-js@latest/dist/clerk.browser.js"
    type="text/javascript"
  ></script>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Geist:wght@400;500;600;700&display=swap');
    
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    
    body {{
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #f7f7f4; /* Warm background matching frontend */
      color: #0f0f10;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 20px;
    }}
    
    .card {{
      background: #ffffff;
      border: 1px solid rgba(0, 0, 0, 0.06);
      border-radius: 12px;
      padding: 40px;
      width: 100%;
      max-width: 440px;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02), 0 20px 48px -20px rgba(0, 0, 0, 0.06);
    }}
    
    .brand {{
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 24px;
    }}
    
    .brand-dot {{
      width: 36px;
      height: 36px;
      background: #101012;
      border-radius: 8px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 18px;
      font-weight: 700;
      color: #fff;
      font-family: 'Geist', sans-serif;
    }}
    
    .brand-name {{
      font-family: 'Geist', sans-serif;
      font-size: 20px;
      font-weight: 600;
      color: #0f0f10;
      letter-spacing: -0.03em;
    }}
    
    .brand-sub {{
      font-size: 12px;
      color: #6b6b70;
    }}
    
    h1 {{
      font-family: 'Geist', sans-serif;
      font-size: 22px;
      font-weight: 600;
      color: #0f0f10;
      margin-bottom: 8px;
      letter-spacing: -0.03em;
    }}
    
    p.subtitle {{
      font-size: 14px;
      color: #6b6b70;
      margin-bottom: 28px;
      line-height: 1.5;
    }}
    
    #clerk-sign-in {{
      display: block;
    }}
       .status {{
      text-align: center;
      padding: 32px 24px;
      border-radius: 12px;
      background: #fafafa;
      border: 1px solid rgba(0, 0, 0, 0.06);
      display: none;
      animation: fadeIn 0.3s cubic-bezier(0.16, 1, 0.3, 1);
    }}
    
    @keyframes fadeIn {{
      from {{ opacity: 0; transform: translateY(4px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}
    
    .status.show {{
      display: block;
    }}
    
    .status-icon-container {{
      margin-bottom: 16px;
      display: flex;
      justify-content: center;
      align-items: center;
    }}
    
    .success-icon {{
      width: 40px;
      height: 40px;
      background: #ecfdf5;
      border: 1px solid #d1fae5;
      border-radius: 50%;
      color: #10b981;
      display: none;
      align-items: center;
      justify-content: center;
      animation: scaleIn 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
      margin: 0 auto;
    }}
    
    .success-icon svg {{
      width: 20px;
      height: 20px;
    }}
    
    @keyframes scaleIn {{
      from {{ transform: scale(0.8); opacity: 0; }}
      to {{ transform: scale(1); opacity: 1; }}
    }}
    
    .status h2 {{
      font-family: 'Geist', sans-serif;
      font-size: 15px;
      font-weight: 600;
      color: #0f0f10;
      margin-bottom: 6px;
      letter-spacing: -0.02em;
    }}
    
    .status p {{
      margin-bottom: 0;
      color: #6b6b70;
      font-size: 13px;
      line-height: 1.4;
    }}
    
    .status.error {{
      background: #fdf2f2;
      border-color: #fde8e8;
    }}
    
    .status.error h2 {{
      color: #dc2626;
    }}
    
    .status.error p {{
      color: #9b1c1c;
    }}
    
    .spinner {{
      width: 32px;
      height: 32px;
      border: 3px solid rgba(0, 0, 0, 0.05);
      border-top-color: #101012;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
      margin: 0 auto;
    }}
    
    @keyframes spin {{
      to {{ transform: rotate(360deg); }}
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="brand">
      <div class="brand-dot">N</div>
      <div>
        <div class="brand-name">Nipuna AI</div>
        <div class="brand-sub">Tally Connector</div>
      </div>
    </div>
    <h1>Sign in to continue</h1>
    <p class="subtitle">Authorize the Nipuna Desktop app to connect your Tally data to Nipuna AI.</p>
    <div id="clerk-sign-in"></div>
    <div id="status" class="status">
      <div class="status-icon-container">
        <div class="spinner" id="spinner"></div>
        <div class="success-icon" id="success-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="20 6 9 17 4 12"></polyline>
          </svg>
        </div>
      </div>
      <h2 id="status-title">Authenticating...</h2>
      <p id="status-msg">Please wait while we set up your connection.</p>
    </div>
  </div>
  <script>
    const params = new URLSearchParams(window.location.search);
    const redirectUri = params.get('redirect_uri') || '';
    let authDone = false;

    function showStatus(type, title, msg) {{
      const signInEl = document.getElementById('clerk-sign-in');
      if (signInEl) signInEl.style.display = 'none';
      
      const statusEl = document.getElementById('status');
      statusEl.classList.add('show');
      
      const spinner = document.getElementById('spinner');
      const successIcon = document.getElementById('success-icon');
      
      statusEl.classList.remove('error');
      
      if (type === 'loading') {{
        spinner.style.display = 'block';
        successIcon.style.display = 'none';
      }} else if (type === 'success') {{
        spinner.style.display = 'none';
        successIcon.style.display = 'flex';
      }} else if (type === 'error') {{
        spinner.style.display = 'none';
        successIcon.style.display = 'none';
        statusEl.classList.add('error');
      }}
      
      document.getElementById('status-title').textContent = title;
      document.getElementById('status-msg').textContent = msg;
    }}

    async function handleAuthenticated(clerk) {{
      if (authDone) return;
      authDone = true;
      showStatus('loading', 'Authenticating\u2026', 'Please wait while we set up your connection.');
      try {{
        const token = await clerk.session.getToken();
        if (!token) throw new Error('Could not get session token. Please try again.');
        const resp = await fetch('/api/v1/desktop/token', {{
          method: 'POST',
          headers: {{ 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' }},
        }});
        if (!resp.ok) throw new Error('Backend error ' + resp.status + '. Is the backend running?');
        const data = await resp.json();
        showStatus('success', 'Connected!', 'Redirecting back to Nipuna Desktop\u2026');
        setTimeout(() => {{
          if (redirectUri) {{
            window.location.href = redirectUri + '?token=' + encodeURIComponent(data.token);
          }}
        }}, 800);
      }} catch (e) {{
        authDone = false;
        showStatus('error', 'Something went wrong', e.message);
      }}
    }}

    window.addEventListener('load', async () => {{
      await window.Clerk.load();
      const clerk = window.Clerk;

      if (clerk.user) {{
        // Already signed in (page reloaded with existing session)
        await handleAuthenticated(clerk);
        return;
      }}

      // Use routing:'virtual' so Clerk NEVER navigates away from this page.
      clerk.mountSignIn(document.getElementById('clerk-sign-in'), {{
        routing: 'virtual',
      }});

      clerk.addListener(async ({{ user }}) => {{
        if (user) await handleAuthenticated(clerk);
      }});
    }});
  </script>
</body>
</html>
"""



@page_router.get("/desktop-auth", response_class=HTMLResponse, include_in_schema=False)
async def desktop_auth_page(redirect_uri: str = Query(default="")) -> HTMLResponse:
    """Serves the Clerk sign-in page for desktop app authentication."""
    html = DESKTOP_AUTH_HTML.format(
        clerk_publishable_key=CLERK_PUBLISHABLE_KEY,
        clerk_domain=CLERK_DOMAIN,
    )
    return HTMLResponse(content=html)


@router.post("/token")
async def issue_desktop_token(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Issues a short-lived (5 min) opaque token for the desktop app OAuth callback."""
    now = time.time()
    # Purge expired tokens
    expired = [k for k, v in _desktop_tokens.items() if v["expires_at"] < now]
    for k in expired:
        del _desktop_tokens[k]

    auth_header = request.headers.get("authorization", "")
    clerk_jwt = auth_header.removeprefix("Bearer ").strip()

    opaque_token = uuid.uuid4().hex
    _desktop_tokens[opaque_token] = {
        "clerk_jwt": clerk_jwt,
        "expires_at": now + 300,
        "user_id": str(user.id),
    }
    logger.info("Issued desktop token for user %s", user.id)
    return {"token": opaque_token}


class ExchangeRequest(BaseModel):
    token: str


@router.post("/exchange")
async def exchange_desktop_token(body: ExchangeRequest) -> dict:
    """Exchanges a one-time opaque token for the Clerk JWT. Used by the desktop app."""
    stored = _desktop_tokens.get(body.token)
    if not stored:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if stored["expires_at"] < time.time():
        del _desktop_tokens[body.token]
        raise HTTPException(status_code=401, detail="Token expired")
    del _desktop_tokens[body.token]  # one-time use
    logger.info("Desktop token exchanged for user %s", stored["user_id"])
    return {"clerk_jwt": stored["clerk_jwt"]}
