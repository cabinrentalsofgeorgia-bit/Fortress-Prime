"""
FORTRESS PRIME — Unified Navigation Component
================================================
Shared navigation bar injected into all dashboards.
Every page links back to Command Center and out to all services.

Usage in any FastAPI dashboard:
    from fortress_nav import inject_nav
    html = inject_nav(raw_html, active="legal")
"""

# The navigation bar HTML + CSS that gets injected into every dashboard.
# Uses absolute URLs so it works regardless of which port you're on.

import os

HOST = os.getenv("BASE_IP", "192.168.0.100")

NAV_ITEMS = [
    {"id": "command",   "label": "Command Center",   "port": 9800,  "icon": "&#9733;"},
    {"id": "legal",     "label": "Legal CRM",         "port": 9878,  "icon": "&#9878;"},
    {"id": "health",    "label": "System Health",      "port": 9876,  "icon": "&#9881;"},
    {"id": "classify",  "label": "Classifier",         "port": 9877,  "icon": "&#9783;"},
    {"id": "grafana",   "label": "Grafana",            "port": 3000,  "icon": "&#9776;"},
    {"id": "portainer", "label": "Portainer",          "port": 8888,  "icon": "&#9638;"},
    {"id": "mission",   "label": "Mission Control",    "port": 8080,  "icon": "&#9798;"},
]


def get_nav_css() -> str:
    return """
/* ── FORTRESS UNIFIED NAV ── */
.fn-bar{background:#0a0a0a;border-bottom:1px solid #1a1a1a;padding:0 16px;
  display:flex;align-items:center;height:36px;font-family:system-ui,-apple-system,sans-serif;
  position:sticky;top:0;z-index:9999;gap:0;flex-shrink:0;
  box-shadow:0 1px 3px rgba(0,0,0,.3)}
.fn-home{display:flex;align-items:center;gap:6px;color:#fff;text-decoration:none;
  font-weight:700;font-size:12px;letter-spacing:.03em;padding:6px 12px 6px 0;
  border-right:1px solid #222;margin-right:4px;white-space:nowrap;transition:color .15s}
.fn-home:hover{color:#4ade80}
.fn-home svg{opacity:.6}
.fn-links{display:flex;align-items:center;gap:0;overflow-x:auto;scrollbar-width:none;flex:1}
.fn-links::-webkit-scrollbar{display:none}
.fn-link{display:flex;align-items:center;gap:5px;padding:8px 12px;color:#888;
  text-decoration:none;font-size:11px;font-weight:500;white-space:nowrap;
  border-bottom:2px solid transparent;transition:all .15s;letter-spacing:.01em}
.fn-link:hover{color:#fff;background:rgba(255,255,255,.04)}
.fn-link.fn-active{color:#fff;border-bottom-color:#4ade80}
.fn-link .fn-icon{font-size:13px;opacity:.5}
.fn-right{margin-left:auto;display:flex;align-items:center;gap:8px;flex-shrink:0}
.fn-dot{width:6px;height:6px;border-radius:50%;background:#4ade80;
  box-shadow:0 0 6px #4ade80;animation:fn-pulse 2s ease infinite}
@keyframes fn-pulse{0%,100%{opacity:1}50%{opacity:.4}}
.fn-clock{font-size:10px;color:#555;font-family:'SF Mono',Consolas,monospace}
@media(max-width:768px){
  .fn-link span:not(.fn-icon){display:none}
  .fn-link{padding:8px 8px}
}
"""


def get_nav_html(active: str = "") -> str:
    links = ""
    for item in NAV_ITEMS:
        cls = "fn-link fn-active" if item["id"] == active else "fn-link"
        links += (
            f'<a href="http://{HOST}:{item["port"]}" class="{cls}">'
            f'<span class="fn-icon">{item["icon"]}</span>'
            f'<span>{item["label"]}</span></a>'
        )

    return f"""<div class="fn-bar">
  <a href="http://{HOST}:9800" class="fn-home">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
      <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>
    </svg>
    FORTRESS PRIME
  </a>
  <div class="fn-links">{links}</div>
  <div class="fn-right">
    <div class="fn-dot"></div>
    <span class="fn-clock" id="fnClock"></span>
  </div>
</div>
<script>
(function(){{var c=document.getElementById('fnClock');if(c)setInterval(function(){{c.textContent=new Date().toLocaleTimeString('en-US',{{hour:'2-digit',minute:'2-digit',second:'2-digit'}})}},1000)}})();
</script>"""


def get_nav_fragment(active: str = "") -> str:
    """Return the full CSS + HTML for the nav bar."""
    return f"<style>{get_nav_css()}</style>\n{get_nav_html(active)}"


def inject_nav(html: str, active: str = "") -> str:
    """Inject the unified nav bar into an existing HTML page.

    Inserts right after <body> tag. If the page already has a fn-bar, skip.
    """
    if "fn-bar" in html:
        return html  # Already injected

    fragment = get_nav_fragment(active)

    # Try to insert after <body...>
    import re
    body_match = re.search(r'(<body[^>]*>)', html, re.IGNORECASE)
    if body_match:
        pos = body_match.end()
        return html[:pos] + "\n" + fragment + "\n" + html[pos:]

    # Fallback: prepend
    return fragment + "\n" + html
