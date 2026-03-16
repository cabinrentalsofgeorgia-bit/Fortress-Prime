"""
Email delivery service — SMTP with graceful fallback.
If SMTP is not configured, invite links are logged to console.

Supports optional file attachments via MIMEMultipart("mixed") nesting.
"""
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import structlog

from backend.core.config import settings

logger = structlog.get_logger()


def is_email_configured() -> bool:
    return bool(settings.smtp_user and settings.smtp_password)


def send_email(
    to: str,
    subject: str,
    html_body: str,
    text_body: str = "",
    attachments: Optional[list[dict]] = None,
) -> bool:
    """
    Send an email with optional PDF attachments.

    When attachments are present the MIME tree is:
        mixed (root)
        ├── alternative (text + html bodies)
        │   ├── text/plain
        │   └── text/html
        ├── application/pdf  (attachment 1)
        └── application/pdf  (attachment 2)

    Each attachment dict: {"filename": str, "content": bytes, "mime_type": str}
    """
    if not is_email_configured():
        logger.warning("email_not_configured", to=to, subject=subject)
        return False

    from_addr = f"{settings.email_from_name} <{settings.email_from_address or settings.smtp_user}>"

    if attachments:
        msg = MIMEMultipart("mixed")
        alt_part = MIMEMultipart("alternative")
        if text_body:
            alt_part.attach(MIMEText(text_body, "plain"))
        alt_part.attach(MIMEText(html_body, "html"))
        msg.attach(alt_part)

        for att in attachments:
            maintype, subtype = att.get("mime_type", "application/pdf").split("/", 1)
            part = MIMEBase(maintype, subtype)
            part.set_payload(att["content"])
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition", "attachment",
                filename=att.get("filename", "document.pdf"),
            )
            msg.attach(part)
    else:
        msg = MIMEMultipart("alternative")
        if text_body:
            msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

    msg["From"] = from_addr
    msg["To"] = to
    msg["Subject"] = subject

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        logger.info(
            "email_sent", to=to, subject=subject,
            attachments=len(attachments) if attachments else 0,
        )
        return True
    except Exception as e:
        logger.error("email_send_failed", to=to, error=str(e))
        return False


def send_invite_email(
    to: str,
    first_name: str,
    invite_url: str,
    invited_by_name: str,
    role: str,
    expires_hours: int = 72,
) -> bool:
    subject = "You're invited to Fortress Guest Platform"

    html_body = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f4f4f5;">
  <table width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;margin:40px auto;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.1);">
    <tr>
      <td style="background:#18181b;padding:28px 32px;text-align:center;">
        <h1 style="margin:0;color:#ffffff;font-size:20px;font-weight:600;letter-spacing:-0.025em;">
          Fortress Guest Platform
        </h1>
      </td>
    </tr>
    <tr>
      <td style="padding:32px;">
        <h2 style="margin:0 0 8px;color:#18181b;font-size:18px;">
          Hi {first_name},
        </h2>
        <p style="margin:0 0 20px;color:#52525b;font-size:15px;line-height:1.6;">
          <strong>{invited_by_name}</strong> has invited you to join the Fortress Guest Platform
          as <strong style="text-transform:capitalize;">{role}</strong>.
        </p>
        <p style="margin:0 0 24px;color:#52525b;font-size:15px;line-height:1.6;">
          Click the button below to create your account and set your password.
        </p>
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td align="center">
              <a href="{invite_url}"
                 style="display:inline-block;background:#18181b;color:#ffffff;text-decoration:none;padding:12px 32px;border-radius:8px;font-size:15px;font-weight:600;">
                Accept Invitation
              </a>
            </td>
          </tr>
        </table>
        <p style="margin:24px 0 0;color:#a1a1aa;font-size:13px;line-height:1.5;">
          This invitation expires in <strong>{expires_hours} hours</strong>.
          If you didn't expect this, you can safely ignore this email.
        </p>
        <hr style="border:none;border-top:1px solid #e4e4e7;margin:24px 0;">
        <p style="margin:0;color:#a1a1aa;font-size:12px;">
          If the button doesn't work, copy and paste this link into your browser:<br>
          <a href="{invite_url}" style="color:#3b82f6;word-break:break-all;">{invite_url}</a>
        </p>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    text_body = (
        f"Hi {first_name},\n\n"
        f"{invited_by_name} has invited you to join the Fortress Guest Platform as {role}.\n\n"
        f"Accept your invitation: {invite_url}\n\n"
        f"This link expires in {expires_hours} hours.\n"
    )

    sent = send_email(to, subject, html_body, text_body)

    if not sent:
        logger.warning(
            "invite_email_fallback",
            to=to,
            invite_url=invite_url,
            note="Email not sent — use this URL to accept the invite manually",
        )

    return sent
