"""
Template Engine — Jinja2-based email template rendering and preview.
"""
from typing import Dict, Any
from jinja2 import Environment, BaseLoader, TemplateSyntaxError
import structlog

logger = structlog.get_logger()

_jinja_env = Environment(loader=BaseLoader(), autoescape=False)

SAMPLE_VARIABLES = {
    "guest_name": "Jane Doe",
    "guest_first_name": "Jane",
    "guest_last_name": "Doe",
    "guest_email": "jane@example.com",
    "guest_phone": "+1 (555) 123-4567",
    "property_name": "Mountain View Lodge",
    "check_in_date": "2026-03-15",
    "check_out_date": "2026-03-20",
    "num_guests": "4",
    "total_amount": "$1,250.00",
    "balance_due": "$625.00",
    "confirmation_code": "SC-12345",
    "access_code": "4821",
    "nightly_rate": "$250.00",
    "num_nights": "5",
    "company_name": "Cabin Rentals of Georgia",
}


def render_template(template_str: str, variables: Dict[str, Any] = None) -> str:
    """Render a Jinja2 template string with the given variables."""
    if not template_str:
        return ""
    try:
        tpl = _jinja_env.from_string(template_str)
        return tpl.render(**(variables or SAMPLE_VARIABLES))
    except TemplateSyntaxError as e:
        logger.warning("template_syntax_error", error=str(e))
        return f"[Template Error: {e}]"
    except Exception as e:
        logger.warning("template_render_error", error=str(e))
        return template_str


def preview_template(subject_template: str, body_template: str) -> Dict[str, str]:
    """Render both subject and body with sample data for preview."""
    return {
        "subject": render_template(subject_template),
        "body": render_template(body_template),
        "variables_used": list(SAMPLE_VARIABLES.keys()),
    }
