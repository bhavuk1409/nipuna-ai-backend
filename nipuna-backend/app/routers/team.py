from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_org, get_current_user
from app.models.organization import Organization
from app.models.user import User
from app.schemas.team import InviteRequest, MemberResponse, TeamResponse
from app.services.notifications.email import send_email

router = APIRouter(prefix="/team", tags=["team"])



@router.get("/members", response_model=TeamResponse)
async def get_team_members(
    org: Organization = Depends(get_current_org),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TeamResponse:
    seats_used_result = await db.execute(
        select(func.count(User.id)).where(
            User.org_id == org.id,
            User.status.in_(["active", "pending"]),
        )
    )
    seats_used = seats_used_result.scalar() or 0

    admin_count_result = await db.execute(
        select(func.count(User.id)).where(
            User.org_id == org.id,
            User.role == "admin",
        )
    )
    admin_count = admin_count_result.scalar() or 0

    pending_result = await db.execute(
        select(func.count(User.id)).where(
            User.org_id == org.id,
            User.status == "pending",
        )
    )
    pending_reviews = pending_result.scalar() or 0

    members_result = await db.execute(
        select(User).where(
            User.org_id == org.id,
            User.status != "suspended",
        )
    )
    members = members_result.scalars().all()

    return TeamResponse(
        seats_used=seats_used,
        max_seats=org.seats_max,
        admin_count=admin_count,
        pending_reviews=pending_reviews,
        members=[MemberResponse.model_validate(m) for m in members],
    )


@router.post("/invite", response_model=dict[str, str])
async def invite_member(
    body: InviteRequest,
    org: Organization = Depends(get_current_org),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    seats_result = await db.execute(
        select(func.count(User.id)).where(
            User.org_id == org.id,
            User.status.in_(["active", "pending"]),
        )
    )
    seats_used = seats_result.scalar() or 0
    if seats_used >= org.seats_max:
        raise HTTPException(status_code=400, detail="Seat limit reached")

    settings = get_settings()
    # Always invite as 'member' — role selection is removed from the UI
    body.role = "member"
    clerk_role = body.role
    import httpx
    import logging

    logger = logging.getLogger(__name__)
    
    # Check if user is already in org
    existing_user_result = await db.execute(
        select(User).where(User.org_id == org.id, User.email == body.email)
    )
    if existing_user_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="User is already a member of this organization")

    # Check if the user already has an active/registered account on Nipuna AI
    has_account = False
    existing_clerk_user_id = None
    existing_user = None
    
    local_check = await db.execute(
        select(User).where(
            User.email == body.email,
            ~User.clerk_user_id.like("invited_%")
        )
    )
    existing_user = local_check.scalars().first()
    if existing_user is not None:
        has_account = True
        existing_clerk_user_id = existing_user.clerk_user_id

    if not has_account and settings.clerk_secret_key:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.clerk.com/v1/users",
                    headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
                    params={"email_address": body.email},
                )
                if resp.status_code == 200:
                    users_list = resp.json()
                    if len(users_list) > 0:
                        has_account = True
                        existing_clerk_user_id = users_list[0].get("id")
        except Exception as e:
            logger.warning(f"Error checking user in Clerk: {e}")

    clerk_invited = False
    if org.clerk_org_id and not org.clerk_org_id.startswith("manual_"):
        if existing_clerk_user_id:
            # Existing user: add directly to Clerk Org memberships
            logger.info(f"Adding existing user {existing_clerk_user_id} directly to Clerk Org {org.clerk_org_id}")
            if settings.clerk_secret_key:
                role_to_clerk = {
                    "admin": "org:admin",
                    "member": "org:member",
                    "viewer": "org:member",
                }
                mapped_role = role_to_clerk.get(body.role, body.role)
                try:
                    async with httpx.AsyncClient() as client:
                        resp = await client.post(
                            f"https://api.clerk.com/v1/organizations/{org.clerk_org_id}/memberships",
                            headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
                            json={
                                "user_id": existing_clerk_user_id,
                                "role": mapped_role,
                            },
                        )
                        if resp.status_code in (200, 201):
                            logger.info("Successfully added user to Clerk organization memberships")
                            clerk_invited = True
                        else:
                            logger.warning(f"Failed to add existing user to Clerk Org memberships: {resp.status_code} - {resp.text}")
                except Exception as e:
                    logger.error(f"Error calling Clerk memberships API: {e}")
        
        # If they weren't added to memberships (new user or failed), send Clerk invitation
        if not clerk_invited:
            logger.info(f"Sending Clerk invite: OrgID={org.clerk_org_id}, Email={body.email}, Role={clerk_role}")
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"https://api.clerk.com/v1/organizations/{org.clerk_org_id}/invitations",
                        headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
                        json={
                            "email_address": body.email,
                            "role": "org:member",  # Clerk only supports org:admin / org:member
                            "redirect_url": f"{settings.frontend_url}/dashboard",
                        },
                    )
                    if resp.status_code in (200, 201):
                        clerk_invited = True
                    else:
                        error_data = resp.json()
                        error_msg = error_data.get("errors", [{}])[0].get("message", "Unknown Clerk error")
                        logger.warning(f"Clerk org invite returned {resp.status_code}: {error_msg}")
            except Exception as e:
                logger.warning(f"Error calling Clerk invitations API: {e}")

    # Always create local DB pending user invitation
    # But skip if the existing user is already tracked (has_account via local DB)
    # to avoid a duplicate pending row for an already-registered user
    import uuid as uuid_mod
    if not (existing_user and existing_user.org_id == org.id):
        # Only create a new pending invite row if one doesn't already exist
        dup_check = await db.execute(
            select(User).where(
                User.email == body.email,
                User.org_id == org.id,
                User.status == "pending",
                User.clerk_user_id.like("invited_%"),
            )
        )
        if dup_check.scalar_one_or_none() is None:
            logger.info(f"Creating local DB pending invitation for Email={body.email}, Role={body.role}")
            new_user = User(
                email=body.email,
                role=body.role,
                status="pending",
                org_id=org.id,
                first_name="",
                last_name="",
                clerk_user_id=f"invited_{uuid_mod.uuid4()}",
            )
            db.add(new_user)
            await db.commit()

    # Create in-app notification for existing Nipuna users so it shows in their bell
    if existing_user and existing_user.org_id:
        from app.models.alert import Alert
        logger.info(f"Creating in-app notification for existing user org_id={existing_user.org_id}")
        new_alert = Alert(
            org_id=existing_user.org_id,
            rule_id="TEAM_INVITATION",
            severity="info",
            message=f"You have been invited to join the workspace '{org.name}' as a {body.role}.",
        )
        db.add(new_alert)
        await db.commit()

    join_url = f"{settings.frontend_url}/sign-in?email={body.email}" if has_account else f"{settings.frontend_url}/sign-up?email={body.email}"

    # Send custom invitation email via Resend
    email_html = f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Invitation to join {org.name} on Nipuna AI</title>
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
      
      body {{
        margin: 0;
        padding: 0;
        background-color: #f8fafc;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        -webkit-font-smoothing: antialiased;
      }}
      
      .wrapper {{
        width: 100%;
        background-color: #f8fafc;
        padding: 40px 20px;
      }}
      
      .container {{
        max-width: 580px;
        margin: 0 auto;
        background-color: #ffffff;
        border: 1px solid #eef0f2;
        border-radius: 16px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.02);
        overflow: hidden;
      }}
      
      .content-padding {{
        padding: 40px 40px 32px 40px;
      }}
      
      .header {{
        padding-bottom: 24px;
        border-bottom: 1px solid #f1f3f5;
        margin-bottom: 32px;
      }}
      
      .header-logo {{
        vertical-align: middle;
        margin-right: 10px;
        width: 24px;
        height: 24px;
      }}
      
      .header-text {{
        font-size: 15px;
        font-weight: 600;
        color: #0f172a;
        vertical-align: middle;
      }}
      
      .help-card {{
        background-color: #f8fafc;
        border-radius: 12px;
        padding: 20px;
        margin-top: 32px;
        margin-bottom: 16px;
      }}
      
      .help-icon-wrapper {{
        float: left;
        width: 40px;
        height: 40px;
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 50%;
        text-align: center;
        margin-right: 16px;
      }}
      
      .help-icon {{
        width: 20px;
        height: 20px;
        margin-top: 9px;
      }}
      
      .help-content {{
        overflow: hidden;
      }}
      
      .help-title {{
        font-size: 13px;
        font-weight: 600;
        color: #0f172a;
        margin: 0 0 4px 0;
      }}
      
      .help-link {{
        font-size: 12px;
        font-weight: 500;
        color: #64748b;
        text-decoration: none;
      }}
      
      .footer {{
        padding: 24px 40px;
        background-color: #ffffff;
        border-top: 1px solid #f1f3f5;
      }}
      
      .footer-col-left {{
        float: left;
        width: 50%;
      }}
      
      .footer-col-right {{
        float: right;
        width: 50%;
        text-align: right;
      }}
      
      .footer-logo {{
        width: 20px;
        height: 20px;
        vertical-align: middle;
        margin-right: 8px;
        opacity: 0.8;
      }}
      
      .footer-brand {{
        font-size: 13px;
        font-weight: 600;
        color: #0f172a;
        vertical-align: middle;
      }}
      
      .footer-sub {{
        font-size: 11px;
        color: #64748b;
        margin-top: 4px;
        font-weight: 400;
      }}
      
      .footer-copy {{
        font-size: 12px;
        color: #64748b;
        margin: 0;
        line-height: 1.6;
      }}
      
      .clearfix::after {{
        content: "";
        clear: both;
        display: table;
      }}
      
      @media screen and (max-width: 600px) {{
        .wrapper {{
          padding: 20px 12px;
        }}
        
        .content-padding {{
          padding: 24px 20px 24px 20px;
        }}
        
        .footer {{
          padding: 20px;
        }}
        
        .footer-col-left, .footer-col-right {{
          float: none;
          width: 100%;
          text-align: left;
        }}
        
        .footer-col-right {{
          margin-top: 16px;
        }}
      }}
    </style>
  </head>
  <body>
    <div class="wrapper">
      <div class="container">
        
        <!-- Email Body Container -->
        <div class="content-padding">
          
          <!-- Header -->
          <div class="header">
            <img class="header-logo" src="https://www.nipunaai.in/logo.png" alt="Nipuna AI" />
            <span class="header-text">Nipuna AI</span>
          </div>
          
          <h1 style="font-size: 32px; font-weight: 700; color: #0f172a; margin: 0 0 12px 0; letter-spacing: -0.025em; line-height: 1.15;">
            Join your team.
          </h1>
          <h2 style="font-size: 20px; font-weight: 600; color: #0f172a; margin: 0 0 16px 0; letter-spacing: -0.02em; line-height: 1.3;">
            You've been invited to join {org.name} on Nipuna AI
          </h2>
          <p style="font-size: 14px; line-height: 1.6; color: #475569; margin: 0 0 24px 0; font-weight: 400;">
            Hello,<br><br>
            You have been invited to join the <strong>{org.name}</strong> workspace on Nipuna AI. Nipuna AI helps teams manage execution, approvals, and enterprise automation coverage with AI-driven agents.
          </p>
          
          <!-- Action Buttons -->
          <div style="margin-top: 32px; margin-bottom: 24px;">
            <a href="{join_url}" style="display: inline-block; background-color: #0f172a; color: #ffffff; text-decoration: none; padding: 12px 24px; font-size: 13px; font-weight: 600; border-radius: 6px; font-family: 'Inter', sans-serif; margin-right: 12px; margin-bottom: 8px;">
              Join Workspace &nbsp; <span style="font-size: 14px; font-weight: 400; vertical-align: middle;">➔</span>
            </a>
            <a href="{settings.frontend_url}/invite/decline?email={body.email}&org_id={org.id}" style="display: inline-block; background-color: #ffffff; color: #dc2626; border: 1px solid #fecaca; text-decoration: none; padding: 12px 24px; font-size: 13px; font-weight: 600; border-radius: 6px; font-family: 'Inter', sans-serif; margin-bottom: 8px;">
              Reject Invitation
            </a>
          </div>
          
          <!-- Help / Documentation Card -->
          <div class="help-card clearfix">
            <div class="help-icon-wrapper">
              <svg class="help-icon" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="#334155">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25" />
              </svg>
            </div>
            <div class="help-content">
              <h4 class="help-title">Need help getting started?</h4>
              <a href="https://nipunaai.in/documentation" class="help-link">View Documentation &nbsp;❯</a>
            </div>
          </div>
          
        </div>
        
        <!-- Footer -->
        <div class="footer clearfix">
          <div class="footer-col-left">
            <div>
              <img class="footer-logo" src="https://www.nipunaai.in/logo.png" alt="" />
              <span class="footer-brand">Nipuna AI</span>
            </div>
            <div class="footer-sub">AI Operating System for Business</div>
          </div>
          <div class="footer-col-right">
            <p class="footer-copy">© 2026 Nipuna AI.<br>All rights reserved.</p>
          </div>
        </div>
        
      </div>
    </div>
  </body>
</html>"""
    await send_email(
        to=body.email,
        subject=f"Invitation to join {org.name} on Nipuna AI",
        html=email_html,
    )

    return {"status": "invitation_sent"}


from pydantic import BaseModel
from typing import Optional

class RemoteInvitationAction(BaseModel):
    org_id: Optional[str] = None


@router.post("/accept", response_model=dict[str, str])
async def accept_invitation(
    body: Optional[RemoteInvitationAction] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    target_org_id = body.org_id if body else None
    
    if target_org_id:
        import uuid
        try:
            target_org_uuid = uuid.UUID(target_org_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid org_id format")
            
        # Find the pending invite for this user under the target organization
        pending_check = await db.execute(
            select(User).where(
                User.email == user.email,
                User.org_id == target_org_uuid,
                User.status == "pending",
                User.clerk_user_id.like("invited_%")
            )
        )
        pending_invite = pending_check.scalar_one_or_none()
        if not pending_invite:
            raise HTTPException(status_code=404, detail="Invitation not found or already accepted")
            
        pending_invite.status = "active"
        db.add(pending_invite)
        await db.commit()
        
        # Sync with Clerk memberships
        from app.models.organization import Organization
        org_res = await db.execute(select(Organization).where(Organization.id == target_org_uuid))
        org = org_res.scalar_one_or_none()
        if org and org.clerk_org_id and not org.clerk_org_id.startswith("manual_") and user.clerk_user_id:
            import httpx
            import logging
            logger = logging.getLogger(__name__)
            settings = get_settings()
            if settings.clerk_secret_key:
                role_to_clerk = {
                    "admin": "org:admin",
                    "member": "org:member",
                    "viewer": "org:member",
                }
                clerk_role = role_to_clerk.get(pending_invite.role, pending_invite.role)
                logger.info(f"Adding user {user.clerk_user_id} to Clerk Org {org.clerk_org_id} with role {clerk_role} on accept")
                try:
                    async with httpx.AsyncClient() as client:
                        resp = await client.post(
                            f"https://api.clerk.com/v1/organizations/{org.clerk_org_id}/memberships",
                            headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
                            json={
                                "user_id": user.clerk_user_id,
                                "role": clerk_role,
                            },
                        )
                        if resp.status_code in (200, 201):
                            logger.info("Successfully added user to Clerk organization memberships on accept")
                        else:
                            logger.warning(f"Failed to add user to Clerk organization memberships on accept: {resp.status_code} - {resp.text}")
                except Exception as e:
                    logger.error(f"Error calling Clerk memberships API on accept: {e}")
                    
        return {"status": "success", "detail": "Invitation accepted"}

    if user.status != "pending":
        raise HTTPException(status_code=400, detail="User is not pending invitation review")
    user.status = "active"
    db.add(user)
    await db.commit()

    # Also sync with Clerk organization if it exists and clerk_user_id is active
    from app.models.organization import Organization
    org_res = await db.execute(select(Organization).where(Organization.id == user.org_id))
    org = org_res.scalar_one_or_none()
    if org and org.clerk_org_id and not org.clerk_org_id.startswith("manual_") and user.clerk_user_id and not user.clerk_user_id.startswith("invited_"):
        import httpx
        import logging
        logger = logging.getLogger(__name__)
        settings = get_settings()
        if settings.clerk_secret_key:
            role_to_clerk = {
                "admin": "org:admin",
                "member": "org:member",
                "viewer": "org:member",
            }
            clerk_role = role_to_clerk.get(user.role, user.role)
            logger.info(f"Adding user {user.clerk_user_id} to Clerk Org {org.clerk_org_id} with role {clerk_role} on accept")
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"https://api.clerk.com/v1/organizations/{org.clerk_org_id}/memberships",
                        headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
                        json={
                            "user_id": user.clerk_user_id,
                            "role": clerk_role,
                        },
                    )
                    if resp.status_code in (200, 201):
                        logger.info("Successfully added user to Clerk organization memberships on accept")
                    else:
                        logger.warning(f"Failed to add user to Clerk organization memberships on accept: {resp.status_code} - {resp.text}")
            except Exception as e:
                logger.error(f"Error calling Clerk memberships API on accept: {e}")

    return {"status": "success", "detail": "Invitation accepted"}


@router.post("/decline", response_model=dict[str, str])
async def decline_invitation(
    body: Optional[RemoteInvitationAction] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    target_org_id = body.org_id if body else None
    
    if target_org_id:
        import uuid
        try:
            target_org_uuid = uuid.UUID(target_org_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid org_id format")
            
        # Find the pending invite for this user under the target organization
        pending_check = await db.execute(
            select(User).where(
                User.email == user.email,
                User.org_id == target_org_uuid,
                User.status == "pending",
                User.clerk_user_id.like("invited_%")
            )
        )
        pending_invite = pending_check.scalar_one_or_none()
        if not pending_invite:
            raise HTTPException(status_code=404, detail="Invitation not found")
            
        pending_invite.status = "declined"
        db.add(pending_invite)
        await db.commit()
        
        # Sync with Clerk (remove from Clerk)
        from app.models.organization import Organization
        org_res = await db.execute(select(Organization).where(Organization.id == target_org_uuid))
        org = org_res.scalar_one_or_none()
        if org and org.clerk_org_id and not org.clerk_org_id.startswith("manual_") and user.clerk_user_id:
            import httpx
            import logging
            logger = logging.getLogger(__name__)
            settings = get_settings()
            if settings.clerk_secret_key:
                logger.info(f"Removing user {user.clerk_user_id} from Clerk Org {org.clerk_org_id} on direct decline")
                try:
                    async with httpx.AsyncClient() as client:
                        resp = await client.delete(
                            f"https://api.clerk.com/v1/organizations/{org.clerk_org_id}/memberships/{user.clerk_user_id}",
                            headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
                        )
                except Exception as e:
                    logger.error(f"Error calling Clerk memberships delete API: {e}")
                    
        return {"status": "success", "detail": "Invitation declined"}

    if user.status != "pending":
        raise HTTPException(status_code=400, detail="User is not pending invitation review")
    
    # Retrieve organization details before committing status change
    from app.models.organization import Organization
    org_res = await db.execute(select(Organization).where(Organization.id == user.org_id))
    org = org_res.scalar_one_or_none()

    user.status = "declined"
    db.add(user)
    await db.commit()

    # Also remove from Clerk organization if it exists and clerk_user_id is active
    if org and org.clerk_org_id and not org.clerk_org_id.startswith("manual_") and user.clerk_user_id and not user.clerk_user_id.startswith("invited_"):
        import httpx
        import logging
        logger = logging.getLogger(__name__)
        settings = get_settings()
        if settings.clerk_secret_key:
            logger.info(f"Removing user {user.clerk_user_id} from Clerk Org {org.clerk_org_id} due to declined invite")
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.delete(
                        f"https://api.clerk.com/v1/organizations/{org.clerk_org_id}/memberships/{user.clerk_user_id}",
                        headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
                    )
                    if resp.status_code == 200:
                        logger.info("Successfully removed user from Clerk organization memberships")
                    else:
                        logger.warning(f"Failed to remove user from Clerk Org memberships: {resp.status_code} - {resp.text}")
            except Exception as e:
                logger.error(f"Error calling Clerk memberships delete API: {e}")

    return {"status": "success", "detail": "Invitation declined"}


@router.post("/public-decline", response_model=dict[str, str])
async def public_decline_invitation(
    email: str,
    org_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    import uuid
    try:
        org_uuid = uuid.UUID(org_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid org_id format")

    result = await db.execute(
        select(User).where(
            User.email == email,
            User.org_id == org_uuid,
            User.status == "pending",
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Pending invitation not found")

    user.status = "declined"
    db.add(user)
    await db.commit()
    return {"status": "success", "detail": "Invitation declined"}


@router.delete("/members/{member_id}", response_model=dict[str, str])
async def remove_member(
    member_id: str,
    org: Organization = Depends(get_current_org),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    import uuid
    try:
        member_uuid = uuid.UUID(member_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid member_id format")

    result = await db.execute(
        select(User).where(
            User.id == member_uuid,
            User.org_id == org.id,
            User.status == "active",
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Active member not found in this organization")

    member.status = "suspended"
    member.org_id = None
    db.add(member)
    await db.commit()
    return {"status": "success", "detail": "Member removed"}


@router.delete("/invitations/{member_id}", response_model=dict[str, str])
async def cancel_invitation(
    member_id: str,
    org: Organization = Depends(get_current_org),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    import uuid
    try:
        member_uuid = uuid.UUID(member_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid member_id format")

    result = await db.execute(
        select(User).where(
            User.id == member_uuid,
            User.org_id == org.id,
            User.status.in_(["pending", "declined"]),
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Pending invitation not found in this organization")

    await db.delete(member)
    await db.commit()
    return {"status": "success", "detail": "Invitation cancelled"}


@router.post("/invitations/{member_id}/resend", response_model=dict[str, str])
async def resend_invitation(
    member_id: str,
    org: Organization = Depends(get_current_org),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    import uuid
    try:
        member_uuid = uuid.UUID(member_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid member_id format")

    result = await db.execute(
        select(User).where(
            User.id == member_uuid,
            User.org_id == org.id,
            User.status.in_(["pending", "declined"]),
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Pending invitation not found in this organization")

    # In dev/prod environment, check if user has an account
    settings = get_settings()
    has_account = False
    existing_clerk_user_id = None
    
    local_check = await db.execute(
        select(User).where(
            User.email == member.email,
            ~User.clerk_user_id.like("invited_%")
        )
    )
    existing_user = local_check.scalars().first()
    if existing_user is not None:
        has_account = True
        existing_clerk_user_id = existing_user.clerk_user_id

    if not has_account and settings.clerk_secret_key:
        import httpx
        import logging
        logger = logging.getLogger(__name__)
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.clerk.com/v1/users",
                    headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
                    params={"email_address": member.email},
                )
                if resp.status_code == 200:
                    users_list = resp.json()
                    if len(users_list) > 0:
                        has_account = True
                        existing_clerk_user_id = users_list[0].get("id")
        except Exception as e:
            logger.warning(f"Error checking user in Clerk: {e}")

    # Re-send Clerk Org invitation if real organization
    clerk_invited = False
    if org.clerk_org_id and not org.clerk_org_id.startswith("manual_"):
        if existing_clerk_user_id:
            logger.info(f"Adding existing user {existing_clerk_user_id} directly to Clerk Org {org.clerk_org_id} on resend")
            if settings.clerk_secret_key:
                role_to_clerk = {
                    "admin": "org:admin",
                    "member": "org:member",
                    "viewer": "org:member",
                }
                mapped_role = role_to_clerk.get(member.role, member.role)
                try:
                    async with httpx.AsyncClient() as client:
                        resp = await client.post(
                            f"https://api.clerk.com/v1/organizations/{org.clerk_org_id}/memberships",
                            headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
                            json={
                                "user_id": existing_clerk_user_id,
                                "role": mapped_role,
                            },
                        )
                        if resp.status_code in (200, 201):
                            logger.info("Successfully added user to Clerk organization memberships on resend")
                            clerk_invited = True
                except Exception as e:
                    logger.error(f"Error calling Clerk memberships API on resend: {e}")
        
        if not clerk_invited:
            logger.info(f"Sending Clerk invite on resend: OrgID={org.clerk_org_id}, Email={member.email}, Role={member.role}")
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"https://api.clerk.com/v1/organizations/{org.clerk_org_id}/invitations",
                        headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
                        json={
                            "email_address": member.email,
                            "role": member.role,
                            "redirect_url": f"{settings.frontend_url}/dashboard",
                        },
                    )
            except Exception as e:
                logger.warning(f"Error calling Clerk invitations API on resend: {e}")

    # Re-send the custom invitation email
    join_url = f"{settings.frontend_url}/sign-in?email={member.email}" if has_account else f"{settings.frontend_url}/sign-up?email={member.email}"
    
    email_html = f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Invitation to join {org.name} on Nipuna AI</title>
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
      
      body {{
        margin: 0;
        padding: 0;
        background-color: #f8fafc;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        -webkit-font-smoothing: antialiased;
      }}
      
      .wrapper {{
        width: 100%;
        background-color: #f8fafc;
        padding: 40px 20px;
      }}
      
      .container {{
        max-width: 580px;
        margin: 0 auto;
        background-color: #ffffff;
        border: 1px solid #eef0f2;
        border-radius: 16px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.02);
        overflow: hidden;
      }}
      
      .content-padding {{
        padding: 40px 40px 32px 40px;
      }}
      
      .header {{
        padding-bottom: 24px;
        border-bottom: 1px solid #f1f3f5;
        margin-bottom: 32px;
      }}
      
      .header-logo {{
        vertical-align: middle;
        margin-right: 10px;
        width: 24px;
        height: 24px;
      }}
      
      .header-text {{
        font-size: 15px;
        font-weight: 600;
        color: #0f172a;
        vertical-align: middle;
      }}
      
      .help-card {{
        background-color: #f8fafc;
        border-radius: 12px;
        padding: 20px;
        margin-top: 32px;
        margin-bottom: 16px;
      }}
      
      .help-icon-wrapper {{
        float: left;
        width: 40px;
        height: 40px;
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        text-align: center;
        line-height: 40px;
      }}
      
      .help-icon {{
        width: 20px;
        height: 20px;
        vertical-align: middle;
      }}
      
      .help-content {{
        margin-left: 56px;
      }}
      
      .help-title {{
        font-size: 13px;
        font-weight: 600;
        color: #0f172a;
        margin: 0 0 2px 0;
      }}
      
      .help-link {{
        font-size: 12px;
        font-weight: 500;
        color: #64748b;
        text-decoration: none;
      }}
      
      .footer {{
        background-color: #f8fafc;
        border-top: 1px solid #eef0f2;
        padding: 32px 40px;
      }}
      
      .footer-col-left {{
        float: left;
        width: 50%;
      }}
      
      .footer-col-right {{
        float: right;
        width: 50%;
        text-align: right;
      }}
      
      .footer-logo {{
        width: 20px;
        height: 20px;
        vertical-align: middle;
        margin-right: 8px;
        opacity: 0.8;
      }}
      
      .footer-brand {{
        font-size: 13px;
        font-weight: 600;
        color: #0f172a;
        vertical-align: middle;
      }}
      
      .footer-sub {{
        font-size: 11px;
        color: #64748b;
        margin-top: 4px;
        font-weight: 400;
      }}
      
      .footer-copy {{
        font-size: 12px;
        color: #64748b;
        margin: 0;
        line-height: 1.6;
      }}
      
      .clearfix::after {{
        content: "";
        clear: both;
        display: table;
      }}
      
      @media screen and (max-width: 600px) {{
        .wrapper {{
          padding: 20px 12px;
        }}
        
        .content-padding {{
          padding: 24px 20px 24px 20px;
        }}
        
        .footer {{
          padding: 20px;
        }}
        
        .footer-col-left, .footer-col-right {{
          float: none;
          width: 100%;
          text-align: left;
        }}
        
        .footer-col-right {{
          margin-top: 16px;
        }}
      }}
    </style>
  </head>
  <body>
    <div class="wrapper">
      <div class="container">
        
        <!-- Email Body Container -->
        <div class="content-padding">
          
          <!-- Header -->
          <div class="header">
            <img class="header-logo" src="https://www.nipunaai.in/logo.png" alt="Nipuna AI" />
            <span class="header-text">Nipuna AI</span>
          </div>
          
          <h1 style="font-size: 32px; font-weight: 700; color: #0f172a; margin: 0 0 12px 0; letter-spacing: -0.025em; line-height: 1.15;">
            Join your team.
          </h1>
          <h2 style="font-size: 20px; font-weight: 600; color: #0f172a; margin: 0 0 16px 0; letter-spacing: -0.02em; line-height: 1.3;">
            Invitation reminder: join {org.name} on Nipuna AI
          </h2>
          <p style="font-size: 14px; line-height: 1.6; color: #475569; margin: 0 0 24px 0; font-weight: 400;">
            Hello,<br><br>
             This is a reminder that you have been invited to join the <strong>{org.name}</strong> workspace on Nipuna AI.
          </p>
          
          <!-- Action Buttons -->
          <div style="margin-top: 32px; margin-bottom: 24px;">
            <a href="{join_url}" style="display: inline-block; background-color: #0f172a; color: #ffffff; text-decoration: none; padding: 12px 24px; font-size: 13px; font-weight: 600; border-radius: 6px; font-family: 'Inter', sans-serif; margin-right: 12px; margin-bottom: 8px;">
              Join Workspace &nbsp; <span style="font-size: 14px; font-weight: 400; vertical-align: middle;">➔</span>
            </a>
            <a href="{settings.frontend_url}/invite/decline?email={member.email}&org_id={org.id}" style="display: inline-block; background-color: #ffffff; color: #dc2626; border: 1px solid #fecaca; text-decoration: none; padding: 12px 24px; font-size: 13px; font-weight: 600; border-radius: 6px; font-family: 'Inter', sans-serif; margin-bottom: 8px;">
              Reject Invitation
            </a>
          </div>
          
          <!-- Help / Documentation Card -->
          <div class="help-card clearfix">
            <div class="help-icon-wrapper">
              <svg class="help-icon" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="#334155">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25" />
              </svg>
            </div>
            <div class="help-content">
              <h4 class="help-title">Need help getting started?</h4>
              <a href="https://nipunaai.in/documentation" class="help-link">View Documentation &nbsp;❯</a>
            </div>
          </div>
          
        </div>
        
        <!-- Footer -->
        <div class="footer clearfix">
          <div class="footer-col-left">
            <div>
              <img class="footer-logo" src="https://www.nipunaai.in/logo.png" alt="" />
              <span class="footer-brand">Nipuna AI</span>
            </div>
            <div class="footer-sub">AI Operating System for Business</div>
          </div>
          <div class="footer-col-right">
            <p class="footer-copy">© 2026 Nipuna AI.<br>All rights reserved.</p>
          </div>
        </div>
        
      </div>
    </div>
  </body>
</html>"""
    
    await send_email(
        to=member.email,
        subject=f"Invitation Reminder to join {org.name} on Nipuna AI",
        html=email_html,
    )
    
    # Update invitation status if it was declined to pending again
    if member.status == "declined":
        member.status = "pending"
        db.add(member)
        await db.commit()

    return {"status": "success", "detail": "Invitation resent"}



