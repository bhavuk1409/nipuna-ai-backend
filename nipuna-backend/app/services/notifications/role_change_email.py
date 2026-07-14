import logging
import uuid
from app.services.notifications.email import send_email

logger = logging.getLogger(__name__)


async def send_role_change_email(
    to_email: str,
    org_name: str,
    role: str,
    updater_name: str,
    logo_url: str | None = None,
    from_email: str = "alerts@nipunaai.in",
) -> None:
    role_display = role.title()
    subject = f"Your role in {org_name} has been updated — Nipuna AI"

    role_description = {
        "admin": "You now have full access to manage members, integrations, and settings.",
        "member": "You can now build workflows, run agents, and collaborate with your team.",
        "viewer": "You now have read-only access to dashboards and reports.",
        "owner": "You now have full ownership and control of the workspace.",
    }.get(role.lower(), f"You now have {role_display} access.")

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
        org_logo_html = f"""
              <table cellpadding="0" cellspacing="0" border="0" style="background: #111111; border-radius: 14px; width: 56px; height: 56px; text-align: center; margin-bottom: 20px;">
                <tr>
                  <td style="font-size: 20px; font-weight: 800; color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; text-align: center; vertical-align: middle; line-height: 56px;">
                    {org_initials}
                  </td>
                </tr>
              </table>
        """

    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Role Updated — Nipuna AI</title>
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

          <!-- Org avatar + status headline -->
          <tr>
            <td style="padding:36px 36px 0;">
              {org_logo_html}
              <h1 style="margin:0 0 8px;font-size:22px;font-weight:800;color:#111111;letter-spacing:-0.5px;line-height:1.2;">
                Role updated in {org_name}
              </h1>
              <p style="margin:0;font-size:15px;color:#6a706f;line-height:1.5;">
                <strong style="color:#111111;">{updater_name}</strong> has updated your permission level inside <strong style="color:#111111;">{org_name}</strong>.
              </p>
            </td>
          </tr>

          <!-- New Role details card -->
          <tr>
            <td style="padding:20px 36px 0;">
              <table cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td style="background:#f7f7f5;border:1px solid #eceeed;border-radius:8px;padding:12px 16px;">
                    <p style="margin:0 0 4px;font-size:10px;font-weight:700;color:#8a8f8e;letter-spacing:0.08em;text-transform:uppercase;">New Role</p>
                    <p style="margin:0;font-size:14px;font-weight:700;color:#111111;">{role_display}</p>
                    <p style="margin:4px 0 0;font-size:12px;color:#6a706f;line-height:1.4;">{role_description}</p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- CTA Button to return to dashboard -->
          <tr>
            <td style="padding:28px 36px 0;">
              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td>
                    <a href="https://nipunaai.in/dashboard"
                       style="display:block;background:#111111;color:#ffffff;font-size:13px;font-weight:700;text-align:center;padding:13px 20px;border-radius:10px;text-decoration:none;letter-spacing:-0.1px;">
                      Open Dashboard
                    </a>
                  </td>
                </tr>
              </table>
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
                      Sent by <strong style="color:#8a8f8e;">Nipuna AI</strong> on behalf of {updater_name}.<br/>
                      If you didn't expect this notification, please contact your workspace owner.
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
            "Sent role update email to %s for org %s (role=%s)",
            to_email,
            org_name,
            role,
        )
    except Exception as e:
        logger.error(
            "Failed to send role update email to %s for org %s: %s",
            to_email,
            org_name,
            e,
        )
