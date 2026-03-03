#!/usr/bin/env python3
"""
Early Bird — Market Intelligence Agent
=========================================
Wakes at 6:00 AM, fetches live market data, consults the Fortress
knowledge base for internal financial context, and synthesizes a
morning briefing via DeepSeek-R1.

Pipeline:
    Live APIs (yfinance, coingecko) -> Market prices
    ChromaDB (fortress_knowledge)   -> Internal financial context
    DeepSeek-R1 (Captain)           -> Synthesized morning briefing

Usage:
    python3 -m src.market_sentinel              # Run briefing
    python3 -m src.market_sentinel --email      # Run + email draft

Crontab:
    0 6 * * * cd /home/admin/Fortress-Prime && python3 -m src.market_sentinel --email >> /mnt/fortress_nas/fortress_data/ai_brain/logs/market_sentinel/daily.log 2>&1
"""

import os
import json
import asyncio
import smtplib
import argparse
import logging
import httpx
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

log = logging.getLogger("market_sentinel")

# Load .env before anything reads env vars
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
except (ImportError, Exception):
    pass

import yfinance as yf
from pycoingecko import CoinGeckoAPI

try:
    from src.event_publisher import EventPublisher, close_event_publisher
    _HAS_EVENT_BUS = True
except ImportError:
    _HAS_EVENT_BUS = False

import chromadb
from langchain_ollama import OllamaEmbeddings

# --- CONFIG ---
# ChromaDB — local NVMe (migrated from /mnt/ai_fast NFS 2026-02-10)
try:
    from src.fortress_paths import CHROMA_PATH as DB_PATH
except ImportError:
    DB_PATH = "/home/admin/fortress_fast/chroma_db"
COLLECTION_NAME = "fortress_knowledge"
EMBED_MODEL = "nomic-embed-text"
REASONING_MODEL = "deepseek-r1:70b"
OLLAMA_URL = "http://localhost:11434"

# Email config — uses Gmail App Password (Google Account > Security > App Passwords)
# Set these in .env or environment: GMAIL_ADDRESS, GMAIL_APP_PASSWORD
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")

# Key tickers to watch
TICKERS = {
    "GC=F": "Gold",
    "^GSPC": "S&P 500",
    "TSLA": "Tesla",
}


# ---------------------------------------------------------------------------
# Data Collection
# ---------------------------------------------------------------------------

def get_market_data() -> dict:
    """Fetches live prices for key assets."""
    print("  Fetching live market data...")
    prices = {}

    # Crypto via CoinGecko
    try:
        cg = CoinGeckoAPI()
        crypto = cg.get_price(ids="bitcoin,ethereum", vs_currencies="usd")
        prices["Bitcoin"] = crypto.get("bitcoin", {}).get("usd", "N/A")
        prices["Ethereum"] = crypto.get("ethereum", {}).get("usd", "N/A")
        print(f"    BTC: ${prices['Bitcoin']:,.0f}  |  ETH: ${prices['Ethereum']:,.0f}")
    except Exception as e:
        print(f"    [WARN] Crypto fetch failed: {e}")
        prices["Bitcoin"] = "unavailable"
        prices["Ethereum"] = "unavailable"

    # Traditional via yfinance
    for symbol, label in TICKERS.items():
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            price = info.get("regularMarketPrice") or info.get("previousClose")
            if price:
                prices[label] = round(price, 2)
                print(f"    {label}: ${price:,.2f}")
            else:
                prices[label] = "unavailable"
                print(f"    {label}: unavailable")
        except Exception as e:
            prices[label] = "unavailable"
            print(f"    {label}: error ({e})")

    return prices


def get_portfolio_context(query: str = "financial holdings and investments") -> str:
    """Retrieves internal financial context from the RAG knowledge base."""
    print(f"  Consulting Fortress Brain: '{query}'...")
    try:
        client = chromadb.PersistentClient(path=DB_PATH)
        embedding_func = OllamaEmbeddings(model=EMBED_MODEL, base_url=OLLAMA_URL)
        collection = client.get_collection(name=COLLECTION_NAME)

        query_vec = embedding_func.embed_query(query)
        results = collection.query(query_embeddings=[query_vec], n_results=5)

        context = ""
        sources = set()
        for i, doc in enumerate(results["documents"][0]):
            meta = results["metadatas"][0][i]
            source = meta.get("source", "Unknown")
            sources.add(source)
            context += f"\n[Source: {source}]\n{doc}\n"

        print(f"    Retrieved {len(results['documents'][0])} chunks from {len(sources)} files.")
        return context
    except Exception as e:
        print(f"    [WARN] RAG query failed: {e}")
        return "(No internal financial context available)"


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------

async def generate_briefing(market_data: dict, internal_context: str) -> str:
    """Synthesizes the morning briefing using DeepSeek-R1 via async httpx."""
    today = datetime.now().strftime("%A, %B %d, %Y")

    prompt = f"""You are the "Early Bird" Market Intelligence Agent for Gary M. Knight,
owner of Cabin Rentals of Georgia and a real estate investor in Blue Ridge, GA.

### LIVE MARKET DATA ({today})
{json.dumps(market_data, indent=2)}

### INTERNAL FINANCIAL CONTEXT (From Gary's Files)
{internal_context}

### INSTRUCTIONS
Write a concise morning briefing (under 300 words):
1. Summarize the key market moves (Gold, BTC, S&P 500, Tesla).
2. Relate these moves to Gary's internal holdings/strategy based on the context provided.
3. Flag any risks or opportunities.
4. End with a 1-sentence "Action Item" recommendation.

Be professional, insightful, and specific. Cite internal file sources when referencing Gary's data."""

    print(f"\n  DeepSeek-R1 synthesizing briefing...\n")

    payload = {
        "model": REASONING_MODEL,
        "prompt": prompt,
        "stream": True,
    }

    briefing = ""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
            async with client.stream(
                "POST", f"{OLLAMA_URL}/api/generate", json=payload
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line:
                        body = json.loads(line)
                        token = body.get("response", "")
                        briefing += token
                        print(token, end="", flush=True)
    except Exception as e:
        log.warning("Briefing generation failed: %s. Degrading gracefully.", e)
        briefing = f"[ERROR] Briefing generation failed: {e}"

    print()
    return briefing


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def save_briefing(briefing: str, market_data: dict):
    """Save the briefing to the NAS logs."""
    log_dir = "/mnt/fortress_nas/fortress_data/ai_brain/logs/market_sentinel"
    os.makedirs(log_dir, exist_ok=True)

    today = datetime.now().strftime("%Y%m%d")
    log_file = os.path.join(log_dir, f"briefing_{today}.md")

    with open(log_file, "w") as f:
        f.write(f"# Early Bird Briefing — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write("## Market Data\n")
        for asset, price in market_data.items():
            f.write(f"- **{asset}**: ${price:,.2f}\n" if isinstance(price, (int, float)) else f"- **{asset}**: {price}\n")
        f.write(f"\n## Analysis\n\n{briefing}\n")

    print(f"\n  Briefing saved to: {log_file}")
    return log_file


def send_via_gmail(subject: str, body: str):
    """
    Dispatches the briefing via Gmail SMTP using an App Password.
    Credentials from env vars: GMAIL_ADDRESS, GMAIL_APP_PASSWORD.
    """
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        print("  [SKIP] Email not configured. Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = f"Fortress Sentinel <{GMAIL_ADDRESS}>"
    msg["To"] = GMAIL_ADDRESS
    msg["Subject"] = subject

    # Plain text version
    msg.attach(MIMEText(body, "plain"))

    # Simple HTML version (wraps in pre for formatting)
    html_body = f"""<html><body>
<h2>{subject}</h2>
<pre style="font-family: Georgia, serif; font-size: 14px; line-height: 1.6;">
{body}
</pre>
<hr>
<p style="color: #888; font-size: 11px;">Generated by Fortress Prime - Early Bird Agent</p>
</body></html>"""
    msg.attach(MIMEText(html_body, "html"))

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"  Email dispatched to {GMAIL_ADDRESS}")
        return True
    except Exception as e:
        print(f"  [WARN] Email failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def broadcast_ticks(prices: dict):
    """Publish live price ticks to the Redpanda event bus."""
    if not _HAS_EVENT_BUS:
        return
    for asset, price in prices.items():
        if price != "unavailable":
            await EventPublisher.publish(
                topic="market.crypto.ticks",
                payload={"asset": asset, "price": price, "source": "market_sentinel"},
                key=asset,
            )


async def async_main(args):
    """Async entry point — fetches data, publishes ticks, generates briefing."""
    print("=" * 60)
    print("  EARLY BIRD — Market Intelligence")
    print(f"  {datetime.now().strftime('%A, %B %d, %Y %H:%M')}")
    print("=" * 60)
    print()

    market = get_market_data()
    print()

    await broadcast_ticks(market)

    context = get_portfolio_context(args.query)
    print()

    print("=" * 60)
    print("  MORNING BRIEFING")
    print("=" * 60)
    briefing = await generate_briefing(market, context)

    print("\n" + "=" * 60)
    save_briefing(briefing, market)

    if args.email:
        subject = f"Early Bird Briefing: {datetime.now().strftime('%A %B %d, %Y')}"
        email_body = f"EARLY BIRD BRIEFING — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        email_body += "=" * 50 + "\n\n"
        email_body += "MARKET SNAPSHOT:\n"
        for asset, price in market.items():
            if isinstance(price, (int, float)):
                email_body += f"  {asset}: ${price:,.2f}\n"
            else:
                email_body += f"  {asset}: {price}\n"
        email_body += "\n" + "=" * 50 + "\n\n"
        email_body += briefing
        send_via_gmail(subject, email_body)

    if _HAS_EVENT_BUS:
        await close_event_publisher()

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Early Bird Market Intelligence Agent")
    parser.add_argument("--email", action="store_true", help="Draft briefing to Gmail")
    parser.add_argument("--query", default="financial holdings investments taxes loans",
                        help="RAG query for internal context")
    args = parser.parse_args()
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
