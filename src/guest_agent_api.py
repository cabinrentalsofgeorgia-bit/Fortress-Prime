#!/usr/bin/env python3
"""
Fortress Prime — Guest Agent API + Review Dashboard
=====================================================
Flask application providing:
1. REST API for processing incoming guest messages
2. Review dashboard for Taylor to approve/edit AI drafts
3. SMS/email delivery pipeline
4. Agent performance metrics

Endpoints:
    GET  /                          — Review dashboard
    GET  /api/queue                 — List pending reviews
    POST /api/queue/:id/approve     — Approve a draft
    POST /api/queue/:id/edit        — Edit and approve
    POST /api/queue/:id/reject      — Reject a draft
    POST /api/incoming              — Process incoming message (webhook)
    GET  /api/stats                 — Agent performance stats
    GET  /api/history/:phone        — Guest conversation history

Usage:
    python src/guest_agent_api.py
    # Dashboard at http://localhost:5050
"""

import sys
import os
import json
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta
from functools import wraps

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, request, jsonify, render_template_string
import psycopg2
from psycopg2.extras import RealDictCursor

from src.guest_agent import GuestAgent, classify_intent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("guest_agent_api")

DB_URL = os.getenv("DATABASE_URL", "")
if not DB_URL:
    _db_host = os.getenv("DB_HOST", "localhost")
    _db_port = os.getenv("DB_PORT", "5432")
    _db_name = os.getenv("DB_NAME", "fortress_db")
    _db_user = os.getenv("DB_USER", "miner_bot")
    _db_pass = os.getenv("DB_PASSWORD", os.getenv("DB_PASS", ""))
    if _db_pass:
        DB_URL = f"postgresql://{_db_user}:{_db_pass}@{_db_host}:{_db_port}/{_db_name}"
    else:
        DB_URL = f"postgresql://{_db_user}@{_db_host}:{_db_port}/{_db_name}"

app = Flask(__name__)
agent = GuestAgent()


def get_db():
    return psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)


# ═══════════════════════════════════════════════════════════════════════
# SMS DELIVERY
# ═══════════════════════════════════════════════════════════════════════

def send_sms(phone_number: str, message: str) -> dict:
    """Send SMS via Twilio (synchronous wrapper)."""
    try:
        from twilio.rest import Client
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")

        sid = os.getenv("TWILIO_ACCOUNT_SID")
        token = os.getenv("TWILIO_AUTH_TOKEN")
        from_phone = os.getenv("TWILIO_PHONE_NUMBER")

        if not all([sid, token, from_phone]):
            return {"success": False, "error": "Twilio credentials not configured"}

        client = Client(sid, token)
        msg = client.messages.create(
            body=message,
            from_=from_phone,
            to=phone_number
        )
        return {"success": True, "sid": msg.sid, "status": msg.status}
    except ImportError:
        return {"success": False, "error": "twilio package not installed"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def log_outbound_message(phone_number: str, message: str, cabin_name: str,
                         queue_id: int, send_result: dict):
    """Log the sent message to message_archive."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO message_archive (
            source, phone_number, message_body, direction, cabin_name,
            response_generated_by, status, sent_at, created_at
        ) VALUES (
            'fortress_agent', %s, %s, 'outbound', %s,
            'ai', %s, NOW(), NOW()
        ) RETURNING id
    """, (
        phone_number, message, cabin_name,
        'sent' if send_result.get("success") else 'failed'
    ))
    msg_id = cur.fetchone()["id"]

    cur.execute("""
        UPDATE agent_response_queue
        SET outbound_message_id = %s, delivery_status = %s, sent_at = NOW(),
            status = 'sent', updated_at = NOW()
        WHERE id = %s
    """, (msg_id, send_result.get("status", "unknown"), queue_id))

    conn.commit()
    conn.close()
    return msg_id


# ═══════════════════════════════════════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@app.route("/api/incoming", methods=["POST"])
def incoming_message():
    """Process an incoming guest message through the AI agent."""
    data = request.json or {}
    phone = data.get("phone_number") or data.get("From", "")
    message = data.get("message") or data.get("Body", "")
    cabin = data.get("cabin_name")

    if not phone or not message:
        return jsonify({"error": "phone_number and message required"}), 400

    result = agent.process_message(phone, message, cabin)

    return jsonify({
        "queue_id": result.queue_id,
        "intent": result.intent.primary,
        "sentiment": result.intent.sentiment,
        "urgency": result.intent.urgency,
        "escalation": result.intent.escalation_required,
        "cabin": result.cabin_name,
        "guest": result.guest_name,
        "confidence": result.confidence_score,
        "model": result.ai_model,
        "duration_ms": result.duration_ms,
        "draft_preview": result.ai_draft[:200],
    })


@app.route("/api/queue", methods=["GET"])
def list_queue():
    """List items in the review queue."""
    status = request.args.get("status", "pending_review")
    limit = int(request.args.get("limit", 50))

    conn = get_db()
    cur = conn.cursor()

    if status == "all":
        cur.execute("""
            SELECT * FROM agent_response_queue
            ORDER BY
                CASE status WHEN 'pending_review' THEN 0 ELSE 1 END,
                urgency_level DESC, created_at ASC
            LIMIT %s
        """, (limit,))
    else:
        cur.execute("""
            SELECT * FROM agent_response_queue
            WHERE status = %s
            ORDER BY urgency_level DESC, created_at ASC
            LIMIT %s
        """, (status, limit))

    items = [dict(r) for r in cur.fetchall()]
    conn.close()

    for item in items:
        for k, v in item.items():
            if isinstance(v, datetime):
                item[k] = v.isoformat()
            elif isinstance(v, (int, float)) and v != v:
                item[k] = None

    return jsonify({"items": items, "count": len(items)})


@app.route("/api/queue/<int:queue_id>/approve", methods=["POST"])
def approve_draft(queue_id):
    """Approve an AI draft and send it."""
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM agent_response_queue WHERE id = %s", (queue_id,))
    item = cur.fetchone()
    if not item:
        conn.close()
        return jsonify({"error": "Not found"}), 404

    message_to_send = item["ai_draft"]

    # Send SMS
    send_result = send_sms(item["phone_number"], message_to_send)

    # Update queue
    cur.execute("""
        UPDATE agent_response_queue
        SET status = 'approved', reviewed_by = 'taylor', reviewed_at = NOW(),
            sent_via = 'sms', updated_at = NOW()
        WHERE id = %s
    """, (queue_id,))
    conn.commit()
    conn.close()

    # Log outbound
    log_outbound_message(
        item["phone_number"], message_to_send,
        item["cabin_name"], queue_id, send_result
    )

    return jsonify({
        "status": "approved_and_sent",
        "send_result": send_result,
        "queue_id": queue_id,
    })


@app.route("/api/queue/<int:queue_id>/edit", methods=["POST"])
def edit_and_approve(queue_id):
    """Edit the AI draft and send the edited version."""
    data = request.json or {}
    edited_text = data.get("edited_draft", "").strip()
    if not edited_text:
        return jsonify({"error": "edited_draft required"}), 400

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM agent_response_queue WHERE id = %s", (queue_id,))
    item = cur.fetchone()
    if not item:
        conn.close()
        return jsonify({"error": "Not found"}), 404

    # Send edited version
    send_result = send_sms(item["phone_number"], edited_text)

    cur.execute("""
        UPDATE agent_response_queue
        SET status = 'edited', reviewed_by = 'taylor', reviewed_at = NOW(),
            edited_draft = %s, sent_via = 'sms', updated_at = NOW()
        WHERE id = %s
    """, (edited_text, queue_id))
    conn.commit()
    conn.close()

    log_outbound_message(
        item["phone_number"], edited_text,
        item["cabin_name"], queue_id, send_result
    )

    return jsonify({
        "status": "edited_and_sent",
        "send_result": send_result,
        "queue_id": queue_id,
    })


@app.route("/api/queue/<int:queue_id>/reject", methods=["POST"])
def reject_draft(queue_id):
    """Reject an AI draft."""
    data = request.json or {}
    reason = data.get("reason", "")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE agent_response_queue
        SET status = 'rejected', reviewed_by = 'taylor', reviewed_at = NOW(),
            review_notes = %s, updated_at = NOW()
        WHERE id = %s
    """, (reason, queue_id))
    conn.commit()
    conn.close()

    return jsonify({"status": "rejected", "queue_id": queue_id})


@app.route("/api/stats", methods=["GET"])
def agent_stats():
    """Agent performance statistics."""
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            count(*) as total,
            count(*) FILTER (WHERE status = 'pending_review') as pending,
            count(*) FILTER (WHERE status = 'approved') as approved,
            count(*) FILTER (WHERE status = 'edited') as edited,
            count(*) FILTER (WHERE status = 'rejected') as rejected,
            count(*) FILTER (WHERE status = 'sent') as sent,
            count(*) FILTER (WHERE escalation_required) as escalations,
            avg(ai_duration_ms) as avg_duration,
            avg(confidence_score) as avg_confidence
        FROM agent_response_queue
    """)
    stats = dict(cur.fetchone())

    cur.execute("""
        SELECT intent, count(*) as cnt
        FROM agent_response_queue
        GROUP BY intent
        ORDER BY cnt DESC
    """)
    stats["by_intent"] = {r["intent"]: r["cnt"] for r in cur.fetchall()}

    cur.execute("""
        SELECT cabin_name, count(*) as cnt
        FROM agent_response_queue
        WHERE cabin_name IS NOT NULL
        GROUP BY cabin_name
        ORDER BY cnt DESC
    """)
    stats["by_cabin"] = {r["cabin_name"]: r["cnt"] for r in cur.fetchall()}

    conn.close()

    for k, v in stats.items():
        if isinstance(v, (int, float)) and v != v:
            stats[k] = None
        elif hasattr(v, '__float__'):
            stats[k] = round(float(v), 2) if v else None

    return jsonify(stats)


@app.route("/api/history/<phone>", methods=["GET"])
def guest_history(phone):
    """Get conversation history for a phone number."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT direction, message_body, cabin_name, sent_at, intent, sentiment,
               response_generated_by
        FROM message_archive
        WHERE phone_number = %s
        ORDER BY COALESCE(sent_at, created_at) DESC
        LIMIT 30
    """, (phone,))
    messages = [dict(r) for r in cur.fetchall()]
    conn.close()

    for msg in messages:
        for k, v in msg.items():
            if isinstance(v, datetime):
                msg[k] = v.isoformat()

    return jsonify({"phone": phone, "messages": messages})


# ═══════════════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════════════

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CROG Guest Agent — Review Dashboard</title>
<style>
  :root {
    --bg: #0f1117; --surface: #1a1d27; --card: #22252f;
    --border: #2e3140; --text: #e4e4e7; --dim: #9ca3af;
    --accent: #3b82f6; --green: #22c55e; --red: #ef4444;
    --orange: #f59e0b; --purple: #a855f7;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.6;
  }
  .header {
    background: var(--surface); border-bottom: 1px solid var(--border);
    padding: 16px 24px; display: flex; align-items: center; justify-content: space-between;
  }
  .header h1 { font-size: 20px; font-weight: 600; }
  .header h1 span { color: var(--accent); }
  .stats-bar {
    display: flex; gap: 24px; font-size: 13px; color: var(--dim);
  }
  .stats-bar .stat { display: flex; align-items: center; gap: 6px; }
  .stats-bar .stat-value { font-weight: 700; color: var(--text); font-size: 16px; }
  .stats-bar .pending .stat-value { color: var(--orange); }
  .stats-bar .approved .stat-value { color: var(--green); }

  .container { max-width: 1200px; margin: 0 auto; padding: 24px; }
  .tabs {
    display: flex; gap: 8px; margin-bottom: 20px;
  }
  .tab {
    padding: 8px 16px; border-radius: 8px; cursor: pointer;
    background: var(--surface); border: 1px solid var(--border);
    color: var(--dim); font-size: 13px; font-weight: 500;
    transition: all 0.15s;
  }
  .tab:hover { border-color: var(--accent); color: var(--text); }
  .tab.active { background: var(--accent); color: white; border-color: var(--accent); }

  .queue-item {
    background: var(--card); border: 1px solid var(--border); border-radius: 12px;
    padding: 20px; margin-bottom: 16px; transition: border-color 0.15s;
  }
  .queue-item:hover { border-color: var(--accent); }
  .queue-item.urgent { border-left: 4px solid var(--red); }
  .queue-item.escalation { border-left: 4px solid var(--orange); }

  .item-header {
    display: flex; justify-content: space-between; align-items: flex-start;
    margin-bottom: 12px;
  }
  .item-meta { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
  .badge {
    padding: 2px 10px; border-radius: 12px; font-size: 11px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.5px;
  }
  .badge-intent { background: rgba(59,130,246,0.15); color: var(--accent); }
  .badge-sentiment-positive { background: rgba(34,197,94,0.15); color: var(--green); }
  .badge-sentiment-negative { background: rgba(239,68,68,0.15); color: var(--red); }
  .badge-sentiment-neutral { background: rgba(156,163,175,0.15); color: var(--dim); }
  .badge-sentiment-urgent { background: rgba(239,68,68,0.3); color: var(--red); }
  .badge-urgency {
    background: rgba(239,68,68,0.15); color: var(--red);
    font-size: 12px;
  }
  .badge-cabin { background: rgba(168,85,247,0.15); color: var(--purple); }
  .badge-escalation { background: rgba(245,158,11,0.3); color: var(--orange); }
  .badge-status-approved { background: rgba(34,197,94,0.2); color: var(--green); }
  .badge-status-edited { background: rgba(59,130,246,0.2); color: var(--accent); }
  .badge-status-rejected { background: rgba(239,68,68,0.2); color: var(--red); }
  .badge-status-sent { background: rgba(34,197,94,0.3); color: var(--green); }

  .guest-info { font-size: 14px; color: var(--dim); }
  .guest-info strong { color: var(--text); }
  .timestamp { font-size: 12px; color: var(--dim); }

  .message-section {
    margin: 12px 0; padding: 12px 16px; border-radius: 8px;
  }
  .guest-message {
    background: rgba(59,130,246,0.08); border: 1px solid rgba(59,130,246,0.2);
  }
  .ai-draft {
    background: rgba(34,197,94,0.08); border: 1px solid rgba(34,197,94,0.2);
  }
  .message-label {
    font-size: 11px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.5px; margin-bottom: 6px; color: var(--dim);
  }
  .message-text { font-size: 14px; white-space: pre-wrap; }

  .actions {
    display: flex; gap: 8px; margin-top: 16px; align-items: center;
  }
  .btn {
    padding: 8px 20px; border-radius: 8px; font-size: 13px; font-weight: 600;
    cursor: pointer; border: none; transition: all 0.15s;
  }
  .btn-approve { background: var(--green); color: white; }
  .btn-approve:hover { background: #16a34a; }
  .btn-edit { background: var(--accent); color: white; }
  .btn-edit:hover { background: #2563eb; }
  .btn-reject { background: transparent; color: var(--red); border: 1px solid var(--red); }
  .btn-reject:hover { background: rgba(239,68,68,0.1); }

  .edit-area {
    display: none; margin-top: 12px;
  }
  .edit-area.active { display: block; }
  .edit-area textarea {
    width: 100%; min-height: 100px; padding: 12px; border-radius: 8px;
    background: var(--surface); border: 1px solid var(--border);
    color: var(--text); font-family: inherit; font-size: 14px; resize: vertical;
  }
  .edit-area textarea:focus { outline: none; border-color: var(--accent); }
  .edit-actions { display: flex; gap: 8px; margin-top: 8px; }

  .confidence-bar {
    width: 60px; height: 6px; background: var(--border); border-radius: 3px;
    overflow: hidden; display: inline-block; vertical-align: middle; margin-left: 4px;
  }
  .confidence-fill { height: 100%; border-radius: 3px; }

  .empty-state {
    text-align: center; padding: 80px 20px; color: var(--dim);
  }
  .empty-state h2 { font-size: 24px; margin-bottom: 8px; color: var(--text); }

  .toast {
    position: fixed; bottom: 24px; right: 24px; padding: 12px 24px;
    border-radius: 8px; font-size: 14px; font-weight: 500;
    transform: translateY(100px); opacity: 0; transition: all 0.3s;
    z-index: 100;
  }
  .toast.show { transform: translateY(0); opacity: 1; }
  .toast.success { background: var(--green); color: white; }
  .toast.error { background: var(--red); color: white; }

  @media (max-width: 768px) {
    .container { padding: 16px; }
    .header { flex-direction: column; gap: 12px; }
    .stats-bar { flex-wrap: wrap; }
    .item-header { flex-direction: column; gap: 8px; }
  }
</style>
</head>
<body>

<div class="header">
  <h1><span>CROG</span> Guest Agent</h1>
  <div class="stats-bar">
    <div class="stat pending">
      <span>Pending:</span>
      <span class="stat-value" id="stat-pending">-</span>
    </div>
    <div class="stat approved">
      <span>Sent Today:</span>
      <span class="stat-value" id="stat-sent">-</span>
    </div>
    <div class="stat">
      <span>Avg Confidence:</span>
      <span class="stat-value" id="stat-confidence">-</span>
    </div>
    <div class="stat">
      <span>Avg Response:</span>
      <span class="stat-value" id="stat-duration">-</span>
    </div>
  </div>
</div>

<div class="container">
  <div class="tabs">
    <div class="tab active" data-status="pending_review">Pending Review</div>
    <div class="tab" data-status="approved">Approved</div>
    <div class="tab" data-status="edited">Edited</div>
    <div class="tab" data-status="rejected">Rejected</div>
    <div class="tab" data-status="all">All</div>
  </div>

  <div id="queue-list"></div>
</div>

<div class="toast" id="toast"></div>

<script>
let currentStatus = 'pending_review';

function showToast(message, type = 'success') {
  const toast = document.getElementById('toast');
  toast.textContent = message;
  toast.className = `toast show ${type}`;
  setTimeout(() => toast.className = 'toast', 3000);
}

function getConfidenceColor(score) {
  if (score >= 0.8) return '#22c55e';
  if (score >= 0.6) return '#f59e0b';
  return '#ef4444';
}

function timeAgo(isoDate) {
  if (!isoDate) return '';
  const diff = Date.now() - new Date(isoDate).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return mins + 'm ago';
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return hrs + 'h ago';
  return Math.floor(hrs / 24) + 'd ago';
}

function renderItem(item) {
  const isUrgent = item.urgency_level >= 4;
  const isEscalation = item.escalation_required;
  const urgencyClass = isUrgent ? ' urgent' : (isEscalation ? ' escalation' : '');
  const conf = item.confidence_score || 0;
  const confColor = getConfidenceColor(conf);

  let statusBadge = '';
  if (item.status !== 'pending_review') {
    statusBadge = `<span class="badge badge-status-${item.status}">${item.status}</span>`;
  }

  let actions = '';
  if (item.status === 'pending_review') {
    actions = `
      <div class="actions">
        <button class="btn btn-approve" onclick="approveItem(${item.id})">Approve & Send</button>
        <button class="btn btn-edit" onclick="toggleEdit(${item.id})">Edit</button>
        <button class="btn btn-reject" onclick="rejectItem(${item.id})">Reject</button>
        <span style="margin-left:auto;font-size:12px;color:var(--dim)">
          Confidence: ${(conf*100).toFixed(0)}%
          <span class="confidence-bar">
            <span class="confidence-fill" style="width:${conf*100}%;background:${confColor}"></span>
          </span>
        </span>
      </div>
      <div class="edit-area" id="edit-${item.id}">
        <textarea id="edit-text-${item.id}">${item.ai_draft}</textarea>
        <div class="edit-actions">
          <button class="btn btn-approve" onclick="editItem(${item.id})">Send Edited</button>
          <button class="btn btn-reject" onclick="toggleEdit(${item.id})">Cancel</button>
        </div>
      </div>
    `;
  }

  const sentDraft = item.edited_draft || item.ai_draft;

  return `
    <div class="queue-item${urgencyClass}">
      <div class="item-header">
        <div>
          <div class="guest-info">
            <strong>${item.guest_name || 'Unknown Guest'}</strong> — ${item.phone_number}
          </div>
          <div class="item-meta" style="margin-top:6px;">
            <span class="badge badge-intent">${item.intent || 'GENERAL'}</span>
            <span class="badge badge-sentiment-${item.sentiment || 'neutral'}">${item.sentiment || 'neutral'}</span>
            ${item.cabin_name ? `<span class="badge badge-cabin">${item.cabin_name}</span>` : ''}
            ${isUrgent ? '<span class="badge badge-urgency">URGENT</span>' : ''}
            ${isEscalation ? '<span class="badge badge-escalation">ESCALATION</span>' : ''}
            ${statusBadge}
          </div>
        </div>
        <div class="timestamp">${timeAgo(item.created_at)}</div>
      </div>

      <div class="message-section guest-message">
        <div class="message-label">Guest Message</div>
        <div class="message-text">${item.guest_message}</div>
      </div>

      <div class="message-section ai-draft">
        <div class="message-label">AI Draft (${item.ai_model || 'unknown'})</div>
        <div class="message-text">${sentDraft}</div>
      </div>

      ${actions}
    </div>
  `;
}

async function loadQueue(status) {
  currentStatus = status;
  document.querySelectorAll('.tab').forEach(t => {
    t.classList.toggle('active', t.dataset.status === status);
  });

  const resp = await fetch(`/api/queue?status=${status}`);
  const data = await resp.json();

  const list = document.getElementById('queue-list');
  if (data.items.length === 0) {
    list.innerHTML = `
      <div class="empty-state">
        <h2>${status === 'pending_review' ? 'All Clear!' : 'No Items'}</h2>
        <p>${status === 'pending_review' ? 'No messages waiting for review.' : `No ${status} items found.`}</p>
      </div>
    `;
  } else {
    list.innerHTML = data.items.map(renderItem).join('');
  }
}

async function loadStats() {
  const resp = await fetch('/api/stats');
  const data = await resp.json();
  document.getElementById('stat-pending').textContent = data.pending || 0;
  document.getElementById('stat-sent').textContent =
    (data.approved || 0) + (data.edited || 0) + (data.sent || 0);
  document.getElementById('stat-confidence').textContent =
    data.avg_confidence ? (data.avg_confidence * 100).toFixed(0) + '%' : '-';
  document.getElementById('stat-duration').textContent =
    data.avg_duration ? Math.round(data.avg_duration) + 'ms' : '-';
}

function toggleEdit(id) {
  const el = document.getElementById(`edit-${id}`);
  el.classList.toggle('active');
}

async function approveItem(id) {
  const resp = await fetch(`/api/queue/${id}/approve`, { method: 'POST' });
  const data = await resp.json();
  if (data.send_result?.success) {
    showToast('Message approved and sent!');
  } else {
    showToast('Approved (SMS: ' + (data.send_result?.error || 'queued') + ')', 'error');
  }
  loadQueue(currentStatus);
  loadStats();
}

async function editItem(id) {
  const text = document.getElementById(`edit-text-${id}`).value.trim();
  if (!text) return;
  const resp = await fetch(`/api/queue/${id}/edit`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ edited_draft: text })
  });
  const data = await resp.json();
  if (data.send_result?.success) {
    showToast('Edited message sent!');
  } else {
    showToast('Edited (SMS: ' + (data.send_result?.error || 'queued') + ')', 'error');
  }
  loadQueue(currentStatus);
  loadStats();
}

async function rejectItem(id) {
  const reason = prompt('Rejection reason (optional):');
  await fetch(`/api/queue/${id}/reject`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ reason: reason || '' })
  });
  showToast('Draft rejected');
  loadQueue(currentStatus);
  loadStats();
}

// Tab click handlers
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => loadQueue(tab.dataset.status));
});

// Initial load + auto-refresh
loadQueue('pending_review');
loadStats();
setInterval(() => {
  loadQueue(currentStatus);
  loadStats();
}, 15000);
</script>

</body>
</html>
"""


@app.route("/")
def dashboard():
    return render_template_string(DASHBOARD_HTML)


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  CROG Guest Agent — Review Dashboard")
    print("  http://localhost:5050")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5050, debug=True)
