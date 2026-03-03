"""
seed_sota_templates.py — Idempotent seeder for 6 SOTA email templates.

Inserts Fortune-500-grade Jinja2 email templates into the email_templates table.
Skips any template whose name already exists (safe to re-run).

Usage:
    cd fortress-guest-platform
    python seed_sota_templates.py
"""

import asyncio
import sys

from sqlalchemy import select

from backend.core.database import AsyncSessionLocal
from backend.models.template import EmailTemplate


TEMPLATES = [
    # ── 1. Dynamic Inquiry Quote ──────────────────────────────────────────
    {
        "name": "Dynamic Inquiry Quote",
        "trigger_event": "inquiry_received",
        "subject_template": "Your Custom Quote for {{ current_state.property_name }} — {{ current_state.check_in_date }} to {{ current_state.check_out_date }}",
        "body_template": """\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f4f4f7;font-family:'Helvetica Neue',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f7;padding:24px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden;">
  <tr><td style="background:#1a1a2e;padding:32px 40px;">
    <h1 style="color:#ffffff;margin:0;font-size:22px;">Cabin Rentals of Georgia</h1>
    <p style="color:#a0aec0;margin:8px 0 0;font-size:14px;">Your Mountain Escape Awaits</p>
  </td></tr>
  <tr><td style="padding:40px;">
    <p style="font-size:16px;color:#2d3748;margin:0 0 16px;">Hi {{ current_state.guest_first_name }},</p>
    <p style="font-size:15px;color:#4a5568;line-height:1.6;">
      Thank you for your interest in <strong>{{ current_state.property_name }}</strong>
      for {{ current_state.check_in_date }} – {{ current_state.check_out_date }}
      ({{ current_state.num_nights }} nights, {{ current_state.num_guests }} guests).
    </p>
{% if current_state.property_demand == 'high' %}
    <div style="background:#fff5f5;border-left:4px solid #e53e3e;padding:12px 16px;margin:16px 0;border-radius:4px;">
      <strong style="color:#e53e3e;">High Demand:</strong>
      <span style="color:#742a2a;">This property has {{ current_state.pending_inquiries }} pending inquiries for these dates. We recommend booking soon.</span>
    </div>
{% endif %}
    <h3 style="color:#1a1a2e;border-bottom:1px solid #e2e8f0;padding-bottom:8px;margin-top:24px;">Quote Breakdown</h3>
    <table width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;color:#4a5568;">
{% for item in current_state.quote_line_items %}
      <tr>
        <td style="padding:8px 0;border-bottom:1px solid #edf2f7;">{{ item.label }}</td>
        <td align="right" style="padding:8px 0;border-bottom:1px solid #edf2f7;">${{ "%.2f"|format(item.amount) }}</td>
      </tr>
{% endfor %}
      <tr>
        <td style="padding:12px 0;font-weight:700;color:#1a1a2e;font-size:16px;">Total</td>
        <td align="right" style="padding:12px 0;font-weight:700;color:#1a1a2e;font-size:16px;">${{ "%.2f"|format(current_state.total_amount) }}</td>
      </tr>
    </table>
    <div style="text-align:center;margin:32px 0;">
      <a href="{{ current_state.checkout_url }}" style="background:#38a169;color:#ffffff;padding:14px 40px;border-radius:6px;text-decoration:none;font-weight:600;font-size:15px;display:inline-block;">Book Now — Lock In This Rate</a>
    </div>
    <p style="font-size:13px;color:#a0aec0;margin-top:24px;">This quote is valid for 48 hours. Pricing may change based on availability.</p>
  </td></tr>
  <tr><td style="background:#f7fafc;padding:24px 40px;text-align:center;">
    <p style="font-size:12px;color:#a0aec0;margin:0;">Cabin Rentals of Georgia, LLC · Blue Ridge, GA · (706) 258-3300</p>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>""",
        "is_active": True,
        "requires_human_approval": True,
    },

    # ── 2. Cart Abandonment Saver ─────────────────────────────────────────
    {
        "name": "Cart Abandonment Saver",
        "trigger_event": "cart_abandoned_2h",
        "subject_template": "{{ current_state.property_name }} is still available — complete your reservation",
        "body_template": """\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f4f4f7;font-family:'Helvetica Neue',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f7;padding:24px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden;">
  <tr><td style="background:#1a1a2e;padding:32px 40px;">
    <h1 style="color:#ffffff;margin:0;font-size:22px;">Cabin Rentals of Georgia</h1>
    <p style="color:#a0aec0;margin:8px 0 0;font-size:14px;">Don't Let This One Get Away</p>
  </td></tr>
  <tr><td style="padding:40px;">
    <p style="font-size:16px;color:#2d3748;margin:0 0 16px;">Hi {{ current_state.guest_first_name }},</p>
    <p style="font-size:15px;color:#4a5568;line-height:1.6;">
      We noticed you were looking at <strong>{{ current_state.property_name }}</strong>
      for {{ current_state.check_in_date }} – {{ current_state.check_out_date }} but didn't finish booking.
    </p>
{% if current_state.availability_remaining <= 3 %}
    <div style="background:#fffbeb;border-left:4px solid #d69e2e;padding:12px 16px;margin:16px 0;border-radius:4px;">
      <strong style="color:#d69e2e;">Limited Availability:</strong>
      <span style="color:#744210;">Only {{ current_state.availability_remaining }} open slot{{ 's' if current_state.availability_remaining != 1 else '' }} left for these dates.</span>
    </div>
{% endif %}
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#f7fafc;border-radius:6px;margin:20px 0;">
      <tr><td style="padding:20px;">
        <p style="margin:0 0 4px;font-weight:600;color:#1a1a2e;font-size:16px;">{{ current_state.property_name }}</p>
        <p style="margin:0 0 4px;color:#4a5568;font-size:14px;">{{ current_state.check_in_date }} – {{ current_state.check_out_date }} · {{ current_state.num_nights }} nights</p>
        <p style="margin:0;font-weight:700;color:#38a169;font-size:18px;">${{ "%.2f"|format(current_state.total_amount) }}</p>
      </td></tr>
    </table>
    <div style="text-align:center;margin:28px 0;">
      <a href="{{ current_state.checkout_url }}" style="background:#38a169;color:#ffffff;padding:14px 40px;border-radius:6px;text-decoration:none;font-weight:600;font-size:15px;display:inline-block;">Complete Your Booking</a>
    </div>
    <p style="font-size:13px;color:#a0aec0;margin-top:16px;">Need help? Reply to this email or call us at (706) 258-3300.</p>
  </td></tr>
  <tr><td style="background:#f7fafc;padding:24px 40px;text-align:center;">
    <p style="font-size:12px;color:#a0aec0;margin:0;">Cabin Rentals of Georgia, LLC · Blue Ridge, GA · (706) 258-3300</p>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>""",
        "is_active": True,
        "requires_human_approval": True,
    },

    # ── 3. Pre-Arrival Concierge ──────────────────────────────────────────
    {
        "name": "Pre-Arrival Concierge",
        "trigger_event": "7_days_before_checkin",
        "subject_template": "Your stay at {{ current_state.property_name }} is in {{ current_state.days_until_checkin }} days — here's your guide",
        "body_template": """\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f4f4f7;font-family:'Helvetica Neue',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f7;padding:24px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden;">
  <tr><td style="background:#1a1a2e;padding:32px 40px;">
    <h1 style="color:#ffffff;margin:0;font-size:22px;">Cabin Rentals of Georgia</h1>
    <p style="color:#a0aec0;margin:8px 0 0;font-size:14px;">Your Pre-Arrival Guide</p>
  </td></tr>
  <tr><td style="padding:40px;">
    <p style="font-size:16px;color:#2d3748;margin:0 0 16px;">Hi {{ current_state.guest_first_name }},</p>
    <p style="font-size:15px;color:#4a5568;line-height:1.6;">
      We're excited to welcome you to <strong>{{ current_state.property_name }}</strong> on
      <strong>{{ current_state.check_in_date }}</strong>! Here's everything you need for a seamless arrival.
    </p>

    <h3 style="color:#1a1a2e;border-bottom:1px solid #e2e8f0;padding-bottom:8px;margin-top:28px;">🏠 Check-In Details</h3>
    <table width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;color:#4a5568;">
      <tr><td style="padding:6px 0;">Check-in Time</td><td align="right" style="padding:6px 0;font-weight:600;">{{ current_state.check_in_time|default('4:00 PM') }}</td></tr>
      <tr><td style="padding:6px 0;">Check-out Time</td><td align="right" style="padding:6px 0;font-weight:600;">{{ current_state.check_out_time|default('10:00 AM') }}</td></tr>
      <tr><td style="padding:6px 0;">Confirmation #</td><td align="right" style="padding:6px 0;font-weight:600;">{{ current_state.confirmation_code }}</td></tr>
{% if current_state.door_code %}
      <tr><td style="padding:6px 0;">Door Code</td><td align="right" style="padding:6px 0;font-weight:600;">{{ current_state.door_code }}</td></tr>
{% endif %}
    </table>

{% if current_state.add_on_experiences %}
    <h3 style="color:#1a1a2e;border-bottom:1px solid #e2e8f0;padding-bottom:8px;margin-top:28px;">✨ Enhance Your Stay</h3>
    <p style="font-size:14px;color:#4a5568;line-height:1.5;">Make your mountain getaway even more special:</p>
    <table width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;">
{% for exp in current_state.add_on_experiences %}
      <tr>
        <td style="padding:10px 0;border-bottom:1px solid #edf2f7;">
          <strong style="color:#2d3748;">{{ exp.name }}</strong><br>
          <span style="color:#718096;font-size:13px;">{{ exp.description }}</span>
        </td>
        <td align="right" style="padding:10px 0;border-bottom:1px solid #edf2f7;white-space:nowrap;">
          <span style="color:#38a169;font-weight:600;">${{ "%.2f"|format(exp.price) }}</span><br>
          <a href="{{ exp.booking_url }}" style="color:#3182ce;font-size:13px;">Add to Stay →</a>
        </td>
      </tr>
{% endfor %}
    </table>
{% endif %}

{% if current_state.directions_url %}
    <div style="text-align:center;margin:32px 0;">
      <a href="{{ current_state.directions_url }}" style="background:#3182ce;color:#ffffff;padding:14px 40px;border-radius:6px;text-decoration:none;font-weight:600;font-size:15px;display:inline-block;">Get Directions</a>
    </div>
{% endif %}
    <p style="font-size:13px;color:#a0aec0;margin-top:24px;">Questions? Reply here or call (706) 258-3300. We're happy to help!</p>
  </td></tr>
  <tr><td style="background:#f7fafc;padding:24px 40px;text-align:center;">
    <p style="font-size:12px;color:#a0aec0;margin:0;">Cabin Rentals of Georgia, LLC · Blue Ridge, GA · (706) 258-3300</p>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>""",
        "is_active": True,
        "requires_human_approval": True,
    },

    # ── 4. Mid-Stay Extension Offer ───────────────────────────────────────
    {
        "name": "Mid-Stay Extension Offer",
        "trigger_event": "2_days_into_stay",
        "subject_template": "Enjoying {{ current_state.property_name }}? Extend your stay at a special rate",
        "body_template": """\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f4f4f7;font-family:'Helvetica Neue',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f7;padding:24px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden;">
  <tr><td style="background:#1a1a2e;padding:32px 40px;">
    <h1 style="color:#ffffff;margin:0;font-size:22px;">Cabin Rentals of Georgia</h1>
    <p style="color:#a0aec0;margin:8px 0 0;font-size:14px;">A Special Offer Just for You</p>
  </td></tr>
  <tr><td style="padding:40px;">
    <p style="font-size:16px;color:#2d3748;margin:0 0 16px;">Hi {{ current_state.guest_first_name }},</p>
    <p style="font-size:15px;color:#4a5568;line-height:1.6;">
      We hope you're having an amazing time at <strong>{{ current_state.property_name }}</strong>!
      Not ready to leave on {{ current_state.check_out_date }}?
    </p>
{% if current_state.extension_available %}
    <div style="background:#f0fff4;border-left:4px solid #38a169;padding:16px 20px;margin:20px 0;border-radius:4px;">
      <p style="margin:0 0 6px;font-weight:700;color:#22543d;font-size:16px;">Extend Your Stay</p>
      <p style="margin:0;color:#2f855a;font-size:14px;">
        {{ current_state.property_name }} is available for
        <strong>{{ current_state.extension_nights_available }} extra night{{ 's' if current_state.extension_nights_available != 1 else '' }}</strong>
        after your current checkout.
      </p>
    </div>
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#f7fafc;border-radius:6px;margin:20px 0;">
      <tr><td style="padding:20px;">
{% for option in current_state.extension_options %}
        <div style="{% if not loop.first %}border-top:1px solid #e2e8f0;padding-top:12px;margin-top:12px;{% endif %}">
          <span style="font-weight:600;color:#1a1a2e;">+{{ option.nights }} night{{ 's' if option.nights != 1 else '' }}</span>
          <span style="color:#718096;"> — new checkout {{ option.new_checkout_date }}</span>
          <span style="float:right;font-weight:700;color:#38a169;">${{ "%.2f"|format(option.price) }}</span>
{% if option.discount_pct %}
          <br><span style="color:#e53e3e;font-size:13px;">{{ option.discount_pct }}% returning-guest discount applied</span>
{% endif %}
        </div>
{% endfor %}
      </td></tr>
    </table>
    <div style="text-align:center;margin:28px 0;">
      <a href="{{ current_state.extension_url }}" style="background:#38a169;color:#ffffff;padding:14px 40px;border-radius:6px;text-decoration:none;font-weight:600;font-size:15px;display:inline-block;">Extend My Stay</a>
    </div>
{% else %}
    <p style="font-size:15px;color:#4a5568;line-height:1.6;">
      Unfortunately, {{ current_state.property_name }} is booked immediately after your stay.
      But we'd love to have you back — reply to this email and we'll help you find the perfect dates for a return trip!
    </p>
{% endif %}
    <p style="font-size:13px;color:#a0aec0;margin-top:24px;">Extension offers are subject to availability and expire 24 hours before your checkout.</p>
  </td></tr>
  <tr><td style="background:#f7fafc;padding:24px 40px;text-align:center;">
    <p style="font-size:12px;color:#a0aec0;margin:0;">Cabin Rentals of Georgia, LLC · Blue Ridge, GA · (706) 258-3300</p>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>""",
        "is_active": True,
        "requires_human_approval": True,
    },

    # ── 5. Post-Checkout Review Router ────────────────────────────────────
    {
        "name": "Post-Checkout Review Router",
        "trigger_event": "1_day_after_checkout",
        "subject_template": "How was your stay at {{ current_state.property_name }}?",
        "body_template": """\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f4f4f7;font-family:'Helvetica Neue',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f7;padding:24px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden;">
  <tr><td style="background:#1a1a2e;padding:32px 40px;">
    <h1 style="color:#ffffff;margin:0;font-size:22px;">Cabin Rentals of Georgia</h1>
    <p style="color:#a0aec0;margin:8px 0 0;font-size:14px;">We'd Love Your Feedback</p>
  </td></tr>
  <tr><td style="padding:40px;">
    <p style="font-size:16px;color:#2d3748;margin:0 0 16px;">Hi {{ current_state.guest_first_name }},</p>
    <p style="font-size:15px;color:#4a5568;line-height:1.6;">
      Thank you for staying at <strong>{{ current_state.property_name }}</strong>!
      We hope you had a wonderful mountain getaway. Your feedback helps us improve —
      and helps future guests find the perfect cabin.
    </p>

{% if current_state.nps_score is defined and current_state.nps_score is not none %}
{% if current_state.nps_score >= 9 %}
    <div style="background:#f0fff4;border-left:4px solid #38a169;padding:16px 20px;margin:20px 0;border-radius:4px;">
      <p style="margin:0 0 8px;font-weight:700;color:#22543d;">We're thrilled you loved it! 🎉</p>
      <p style="margin:0;color:#2f855a;font-size:14px;">Would you share your experience? A quick review goes a long way for our small, family-run business.</p>
    </div>
    <div style="text-align:center;margin:24px 0;">
      <a href="{{ current_state.google_review_url }}" style="background:#4285f4;color:#ffffff;padding:12px 32px;border-radius:6px;text-decoration:none;font-weight:600;font-size:14px;display:inline-block;margin:0 6px;">Review on Google</a>
{% if current_state.vrbo_review_url %}
      <a href="{{ current_state.vrbo_review_url }}" style="background:#3b5998;color:#ffffff;padding:12px 32px;border-radius:6px;text-decoration:none;font-weight:600;font-size:14px;display:inline-block;margin:0 6px;">Review on VRBO</a>
{% endif %}
    </div>
{% elif current_state.nps_score <= 6 %}
    <div style="background:#fff5f5;border-left:4px solid #e53e3e;padding:16px 20px;margin:20px 0;border-radius:4px;">
      <p style="margin:0 0 8px;font-weight:700;color:#742a2a;">We're sorry we fell short.</p>
      <p style="margin:0;color:#9b2c2c;font-size:14px;">Your experience matters to us. We'd like to make it right.</p>
    </div>
    <div style="text-align:center;margin:24px 0;">
      <a href="{{ current_state.private_feedback_url }}" style="background:#e53e3e;color:#ffffff;padding:12px 32px;border-radius:6px;text-decoration:none;font-weight:600;font-size:14px;display:inline-block;">Share Private Feedback</a>
    </div>
{% else %}
    <div style="text-align:center;margin:24px 0;">
      <a href="{{ current_state.survey_url }}" style="background:#38a169;color:#ffffff;padding:14px 40px;border-radius:6px;text-decoration:none;font-weight:600;font-size:15px;display:inline-block;">Leave a Quick Review</a>
    </div>
{% endif %}
{% else %}
    <div style="text-align:center;margin:24px 0;">
      <a href="{{ current_state.survey_url }}" style="background:#38a169;color:#ffffff;padding:14px 40px;border-radius:6px;text-decoration:none;font-weight:600;font-size:15px;display:inline-block;">Share Your Experience</a>
    </div>
{% endif %}

{% if current_state.return_discount_code %}
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#ebf8ff;border-radius:6px;margin:24px 0;">
      <tr><td style="padding:20px;text-align:center;">
        <p style="margin:0 0 6px;font-weight:600;color:#2b6cb0;font-size:15px;">Come Back Soon!</p>
        <p style="margin:0;color:#4a5568;font-size:14px;">Use code <strong style="font-size:18px;color:#2b6cb0;">{{ current_state.return_discount_code }}</strong> for {{ current_state.return_discount_pct }}% off your next stay.</p>
      </td></tr>
    </table>
{% endif %}
    <p style="font-size:13px;color:#a0aec0;margin-top:24px;">Thank you for choosing Cabin Rentals of Georgia. We hope to see you again soon!</p>
  </td></tr>
  <tr><td style="background:#f7fafc;padding:24px 40px;text-align:center;">
    <p style="font-size:12px;color:#a0aec0;margin:0;">Cabin Rentals of Georgia, LLC · Blue Ridge, GA · (706) 258-3300</p>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>""",
        "is_active": True,
        "requires_human_approval": True,
    },

    # ── 6. 11-Month Anniversary Win-Back ─────────────────────────────────
    {
        "name": "11-Month Anniversary Win-Back",
        "trigger_event": "11_months_after_checkout",
        "subject_template": "It's been almost a year, {{ current_state.guest_first_name }} — time for another mountain escape?",
        "body_template": """\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f4f4f7;font-family:'Helvetica Neue',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f7;padding:24px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden;">
  <tr><td style="background:#1a1a2e;padding:32px 40px;">
    <h1 style="color:#ffffff;margin:0;font-size:22px;">Cabin Rentals of Georgia</h1>
    <p style="color:#a0aec0;margin:8px 0 0;font-size:14px;">We Miss You!</p>
  </td></tr>
  <tr><td style="padding:40px;">
    <p style="font-size:16px;color:#2d3748;margin:0 0 16px;">Hi {{ current_state.guest_first_name }},</p>
    <p style="font-size:15px;color:#4a5568;line-height:1.6;">
      Can you believe it's been almost a year since your stay at
      <strong>{{ current_state.previous_property_name }}</strong>
      ({{ current_state.previous_stay_dates }})?
      The mountains are calling — and we have something special for returning guests.
    </p>

{% if current_state.loyalty_discount_pct %}
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#f0fff4;border:2px dashed #38a169;border-radius:8px;margin:24px 0;">
      <tr><td style="padding:24px;text-align:center;">
        <p style="margin:0 0 4px;font-size:13px;color:#38a169;text-transform:uppercase;letter-spacing:1px;font-weight:600;">Returning Guest Exclusive</p>
        <p style="margin:0 0 8px;font-size:32px;font-weight:800;color:#22543d;">{{ current_state.loyalty_discount_pct }}% OFF</p>
        <p style="margin:0 0 12px;color:#2f855a;font-size:14px;">Your next stay at any of our {{ current_state.total_properties }} cabins</p>
        <p style="margin:0;font-size:18px;font-weight:700;color:#1a1a2e;background:#ffffff;display:inline-block;padding:8px 20px;border-radius:4px;letter-spacing:2px;">{{ current_state.loyalty_code }}</p>
      </td></tr>
    </table>
{% endif %}

{% if current_state.recommended_properties %}
    <h3 style="color:#1a1a2e;border-bottom:1px solid #e2e8f0;padding-bottom:8px;margin-top:28px;">Cabins You'll Love</h3>
{% for prop in current_state.recommended_properties %}
    <table width="100%" cellpadding="0" cellspacing="0" style="border-bottom:1px solid #edf2f7;margin-bottom:12px;">
      <tr>
        <td style="padding:12px 0;width:70%;">
          <p style="margin:0 0 4px;font-weight:600;color:#2d3748;">{{ prop.name }}</p>
          <p style="margin:0;font-size:13px;color:#718096;">{{ prop.bedrooms }} BR · Sleeps {{ prop.sleeps }} · {{ prop.highlight }}</p>
        </td>
        <td align="right" style="padding:12px 0;">
          <span style="font-weight:700;color:#38a169;">from ${{ "%.0f"|format(prop.price_per_night) }}/nt</span><br>
          <a href="{{ prop.url }}" style="color:#3182ce;font-size:13px;text-decoration:none;">View Cabin →</a>
        </td>
      </tr>
    </table>
{% endfor %}
{% endif %}

    <div style="text-align:center;margin:32px 0;">
      <a href="{{ current_state.browse_all_url }}" style="background:#38a169;color:#ffffff;padding:14px 40px;border-radius:6px;text-decoration:none;font-weight:600;font-size:15px;display:inline-block;">Browse All Cabins</a>
    </div>
    <p style="font-size:13px;color:#a0aec0;margin-top:24px;">This offer expires in 30 days. Can't make it work? Reply and we'll help find the perfect dates.</p>
  </td></tr>
  <tr><td style="background:#f7fafc;padding:24px 40px;text-align:center;">
    <p style="font-size:12px;color:#a0aec0;margin:0;">Cabin Rentals of Georgia, LLC · Blue Ridge, GA · (706) 258-3300</p>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>""",
        "is_active": True,
        "requires_human_approval": True,
    },
]


async def seed() -> None:
    inserted = 0
    skipped = 0

    async with AsyncSessionLocal() as session:
        for tpl in TEMPLATES:
            result = await session.execute(
                select(EmailTemplate).where(EmailTemplate.name == tpl["name"])
            )
            existing = result.scalar_one_or_none()
            if existing:
                print(f"  SKIP  {tpl['name']!r} (already exists, id={existing.id})")
                skipped += 1
                continue

            row = EmailTemplate(**tpl)
            session.add(row)
            await session.flush()
            print(f"  INSERT {tpl['name']!r} → trigger={tpl['trigger_event']!r}")
            inserted += 1

        await session.commit()

    print(f"\nDone: {inserted} inserted, {skipped} skipped (total templates in seed: {len(TEMPLATES)})")


if __name__ == "__main__":
    asyncio.run(seed())
