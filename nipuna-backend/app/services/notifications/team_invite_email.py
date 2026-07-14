"""Send a workspace-invitation email via Resend.

The team router sends invitation emails via Resend for:
1. Existing users — email points to the dashboard where they can
   accept/decline from the notification bell.
2. Dev `manual_*` orgs — no Clerk org, so we build a self-serve
   share link and email it directly to the invitee.
3. New users (non-Clerk) — Clerk sends a real invitation email.

This module also provides the helper `build_dev_share_link` used
by the team router and the API response to keep the link shape
consistent.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

from app.services.notifications.email import send_email

logger = logging.getLogger(__name__)


async def send_team_invite_email(
    *,
    to_email: str,
    org_name: str,
    inviter_name: str,
    role: str,
    share_link: str,
    logo_url: str | None = None,
    from_email: str = "alerts@nipunaai.in",
) -> bool:
    """Send a workspace-invitation email.

    For existing Nipuna AI users, `share_link` points to the dashboard
    where they'll find the invitation in their notification bell.
    For new users, it points to the `/invite/accept` page.

    Returns True if the Resend API call succeeded, False if it failed.
    We *don't* raise — the team router treats email delivery as
    best-effort and always returns the share link in the response so
    the inviter can copy it manually.
    """
    subject = f"You've been invited to join {org_name} on Nipuna AI"

    role_display = role.capitalize()
    role_description = {
        "admin": "You'll have full access to manage members, integrations, and settings.",
        "member": "You'll be able to build workflows, run agents, and collaborate with your team.",
        "viewer": "You'll have read-only access to dashboards and reports.",
        "owner": "You'll have full ownership and control of the workspace.",
    }.get(role.lower(), f"You'll join as a {role_display}.")

    org_initials = "".join(w[0].upper() for w in org_name.split()[:2]) if org_name else "NA"

    # Render logo or initials fallback (allow both HTTP URLs and inline CID attachments for Base64)
    attachments = None
    email_logo_src = None

    if logo_url:
        if logo_url.startswith("data:image/"):
            try:
                header, base64_data = logo_url.split(",", 1)
                ext = "png"
                if "jpeg" in header or "jpg" in header:
                    ext = "jpg"
                elif "gif" in header:
                    ext = "gif"
                elif "webp" in header:
                    ext = "webp"
                
                attachments = [
                    {
                        "content": base64_data,
                        "filename": f"logo.{ext}",
                        "id": "logo_cid"
                    }
                ]
                email_logo_src = "cid:logo_cid"
            except Exception as e:
                logger.error("Failed to parse Base64 logo: %s", e)
        elif logo_url.startswith("http"):
            email_logo_src = logo_url

    if email_logo_src:
        org_logo_html = f"""
              <table cellpadding="0" cellspacing="0" border="0" style="border-radius: 14px; width: 56px; height: 56px; overflow: hidden; margin-bottom: 20px;">
                <tr>
                  <td style="vertical-align: middle; text-align: center;">
                    <img src="{email_logo_src}" width="56" height="56" style="border-radius: 14px; display: block; border: 0; object-fit: cover;" alt="{org_initials}" />
                  </td>
                </tr>
              </table>
        """
    else:
        org_logo_html = ""


    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Workspace Invitation — Nipuna AI</title>
</head>
<body style="margin:0;padding:0;background:#f7f7f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Inter',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f7f7f5;min-height:100vh;">
    <tr>
      <td align="center" style="padding:40px 16px;">
        <table width="560" cellpadding="0" cellspacing="0" border="0" style="background:#ffffff;border-radius:16px;box-shadow:0 4px 24px rgba(0,0,0,0.06);overflow:hidden;max-width:100%;">

          <!-- Header with logo -->
          <tr>
            <td style="padding:32px 36px 24px;border-bottom:1px solid #f0f1ef;">
              <table cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td width="36" style="vertical-align: middle;">
                    <img src="https://www.nipunaai.in/logo.png" alt="Nipuna AI" width="36" height="36" style="border-radius: 9px; display: block; border: 0;" />
                  </td>
                  <td style="padding-left: 12px; vertical-align: middle; text-align: left;">
                    <span style="font-size: 18px; font-weight: 800; color: #111111; letter-spacing: -0.4px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Inter', Arial, sans-serif; line-height: 36px; display: inline-block;">Nipuna AI</span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Org avatar + invitation headline -->
          <tr>
            <td style="padding:36px 36px 0;">
              {org_logo_html}
              <h1 style="margin:0 0 8px;font-size:22px;font-weight:800;color:#111111;letter-spacing:-0.5px;line-height:1.2;">
                You're invited to join <span style="color:#111111;">{org_name}</span>
              </h1>
              <p style="margin:0;font-size:15px;color:#6a706f;line-height:1.5;">
                <strong style="color:#111111;">{inviter_name}</strong> has invited you to collaborate on <strong style="color:#111111;">{org_name}</strong>.
              </p>
            </td>
          </tr>

          <!-- Role badge -->
          <tr>
            <td style="padding:20px 36px 0;">
              <table cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td style="background:#f7f7f5;border:1px solid #eceeed;border-radius:8px;padding:12px 16px;">
                    <p style="margin:0 0 4px;font-size:10px;font-weight:700;color:#8a8f8e;letter-spacing:0.08em;text-transform:uppercase;">Your Role</p>
                    <p style="margin:0;font-size:14px;font-weight:700;color:#111111;">{role_display}</p>
                    <p style="margin:4px 0 0;font-size:12px;color:#6a706f;line-height:1.4;">{role_description}</p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- CTA Buttons -->
          <tr>
            <td style="padding:28px 36px 0;">
              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td style="padding-right:8px;" width="50%">
                    <a href="{share_link}"
                       style="display:block;background:#111111;color:#ffffff;font-size:13px;font-weight:700;text-align:center;padding:13px 20px;border-radius:10px;text-decoration:none;letter-spacing:-0.1px;">
                      Accept Invitation
                    </a>
                  </td>
                  <td style="padding-left:8px;" width="50%">
                    <a href="{share_link}"
                       style="display:block;background:#ffffff;color:#111111;font-size:13px;font-weight:600;text-align:center;padding:12px 20px;border-radius:10px;text-decoration:none;border:1.5px solid #eceeed;letter-spacing:-0.1px;">
                      View Invitation
                    </a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Note -->
          <tr>
            <td style="padding:20px 36px 0;">
              <p style="margin:0;font-size:12px;color:#8a8f8e;line-height:1.5;text-align:center;">
                If you already have an account, sign in and look for the invitation in your notification bell.<br/>
                This invitation will expire after 7 days.
              </p>
            </td>
          </tr>

          <!-- Divider + Footer -->
          <tr>
            <td style="padding:28px 36px 32px;">
              <hr style="border:none;border-top:1px solid #f0f1ef;margin:0 0 20px;" />
              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td>
                    <p style="margin:0;font-size:11px;color:#b0b5b4;line-height:1.5;">
                      Sent by <strong style="color:#8a8f8e;">Nipuna AI</strong> on behalf of {inviter_name}.<br/>
                      If you didn't expect this invitation, you can safely ignore this email.
                    </p>
                  </td>
                  <td align="right" style="vertical-align:top;">
                    <a href="https://nipunaai.in" style="font-size:11px;color:#b0b5b4;text-decoration:none;">nipunaai.in</a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
    """

    try:
        await send_email(
            to=to_email,
            subject=subject,
            html=html,
            from_email=from_email,
            attachments=attachments,
        )
        logger.info(
            "Sent team invite email to %s for org %s (role=%s)",
            to_email, org_name, role,
        )
        return True
    except Exception as exc:  # send_email already swallows 3x retries
        # send_email itself logs the failure; we just need to mark it.
        logger.warning(
            "send_team_invite_email: Resend call did not succeed for %s: %s",
            to_email, exc,
        )
        return False


def build_dev_share_link(
    frontend_url: str, org_id: str, email: str, org_name: str | None = None,
) -> str:
    """Build the dev self-serve share link for an invite.

    Kept here so the team router and this email module agree on the
    link shape (the frontend's `/invite/accept` page parses it).
    """
    link = (
        f"{frontend_url.rstrip('/')}/invite/accept"
        f"?org_id={quote(org_id)}&email={quote(email)}"
    )
    if org_name:
        link += f"&org_name={quote(org_name)}"
    return link

