"""
PDF Generator — renders signed agreements to professional PDF using WeasyPrint.
Embeds drawn/typed signatures, initials, and a legally-binding audit trail.
"""
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import markdown2
import structlog

logger = structlog.get_logger()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PDF_DIR = Path(os.getenv("PDF_STORAGE_DIR", str(PROJECT_ROOT / "storage" / "agreements")))
PDF_DIR.mkdir(parents=True, exist_ok=True)


def _render_markdown_to_html(md_content: str) -> str:
    return markdown2.markdown(
        md_content,
        extras=["tables", "fenced-code-blocks", "header-ids", "break-on-newline"],
    )


def _signature_img_tag(base64_data: Optional[str], label: str = "Signature") -> str:
    if not base64_data:
        return f'<p style="color:#999;">[{label} not provided]</p>'
    if base64_data.startswith("data:"):
        src = base64_data
    else:
        src = f"data:image/png;base64,{base64_data}"
    return f'<img src="{src}" alt="{label}" style="max-height:60px;max-width:280px;border-bottom:1px solid #333;" />'


def generate_agreement_pdf(
    agreement_id: str,
    rendered_content: str,
    signer_name: str,
    signer_email: str,
    signature_data: Optional[str],
    signature_type: str,
    initials_data: Optional[str],
    initials_pages: Optional[list],
    signer_ip: str,
    signer_user_agent: str,
    signed_at: datetime,
    agreement_type: str = "Rental Agreement",
    property_name: str = "",
    confirmation_code: str = "",
) -> Optional[str]:
    """
    Generate a PDF from the rendered agreement content with embedded signatures.
    Returns the file path or None on failure.
    """
    try:
        from weasyprint import HTML
    except ImportError:
        logger.error("weasyprint_not_installed")
        return None

    body_html = _render_markdown_to_html(rendered_content)

    sig_block = ""
    if signature_type == "drawn":
        sig_block = _signature_img_tag(signature_data, "Signature")
    elif signature_type == "typed":
        sig_block = f'<p style="font-family:\'Dancing Script\',cursive;font-size:28px;color:#1a1a2e;">{signer_name}</p>'
    else:
        sig_block = f'<p style="font-style:italic;">{signer_name}</p>'

    initials_block = ""
    if initials_data:
        initials_block = f"""
        <div style="margin-top:10px;">
            <p style="font-size:11px;color:#666;">Initials:</p>
            {_signature_img_tag(initials_data, "Initials")}
        </div>"""

    audit_line = (
        f"Electronically signed by {signer_name} ({signer_email}) "
        f"on {signed_at.strftime('%B %d, %Y at %I:%M %p UTC')} "
        f"from IP {signer_ip}"
    )

    full_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page {{
    size: letter;
    margin: 1in 0.85in;
    @top-center {{
      content: "{agreement_type} — {property_name}";
      font-size: 9px;
      color: #888;
    }}
    @bottom-center {{
      content: "Page " counter(page) " of " counter(pages);
      font-size: 9px;
      color: #888;
    }}
  }}
  body {{
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    font-size: 12px;
    line-height: 1.6;
    color: #1a1a2e;
  }}
  h1 {{ font-size: 22px; color: #0f172a; border-bottom: 2px solid #2563eb; padding-bottom: 6px; }}
  h2 {{ font-size: 16px; color: #1e293b; margin-top: 24px; }}
  h3 {{ font-size: 13px; color: #334155; }}
  table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
  th, td {{ border: 1px solid #cbd5e1; padding: 6px 10px; text-align: left; font-size: 11px; }}
  th {{ background: #f1f5f9; font-weight: 600; }}
  .sig-block {{
    margin-top: 40px;
    padding: 20px;
    border: 2px solid #2563eb;
    border-radius: 8px;
    background: #f8fafc;
    page-break-inside: avoid;
  }}
  .sig-block h3 {{ color: #2563eb; margin-top: 0; }}
  .audit-trail {{
    margin-top: 30px;
    padding: 12px;
    background: #f1f5f9;
    border-left: 4px solid #2563eb;
    font-size: 10px;
    color: #475569;
    page-break-inside: avoid;
  }}
</style>
</head>
<body>
  <div style="text-align:center;margin-bottom:24px;">
    <h1 style="border:none;margin:0;padding:0;">Cabin Rentals of Georgia</h1>
    <p style="color:#64748b;font-size:11px;margin:4px 0;">
      {agreement_type} &mdash; Confirmation #{confirmation_code}
    </p>
  </div>

  {body_html}

  <div class="sig-block">
    <h3>Signature</h3>
    <table style="border:none;width:100%;">
      <tr style="border:none;">
        <td style="border:none;width:60%;vertical-align:bottom;">
          {sig_block}
          <hr style="border:none;border-top:1px solid #333;margin-top:4px;">
          <p style="font-size:10px;color:#666;">Guest Signature</p>
        </td>
        <td style="border:none;width:40%;vertical-align:bottom;">
          <p style="font-size:14px;">{signed_at.strftime('%B %d, %Y')}</p>
          <hr style="border:none;border-top:1px solid #333;margin-top:4px;">
          <p style="font-size:10px;color:#666;">Date</p>
        </td>
      </tr>
    </table>
    {initials_block}
  </div>

  <div class="audit-trail">
    <strong>Electronic Signature Verification</strong><br>
    {audit_line}<br>
    Agreement ID: {agreement_id}<br>
    User Agent: {signer_user_agent[:120] if signer_user_agent else 'Unknown'}
  </div>
</body>
</html>"""

    filename = f"{agreement_id}.pdf"
    filepath = PDF_DIR / filename

    try:
        HTML(string=full_html).write_pdf(str(filepath))
        logger.info("pdf_generated", agreement_id=agreement_id, path=str(filepath))
        return str(filepath)
    except Exception as e:
        logger.error("pdf_generation_failed", agreement_id=agreement_id, error=str(e))
        return None
