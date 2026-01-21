"""
🛡️ FORTRESS PRIME - Data Enrichment Service
LLM-powered enrichment of market and legal intelligence data.
Automatically extracts structured data from content when new records arrive.
"""

import os
import json
import re
import requests
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from dotenv import load_dotenv

try:
    from sqlalchemy import create_engine, Column, Integer, String, Numeric, Date, Text, DateTime, Enum as SQLEnum
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import sessionmaker
    import enum
except ImportError:
    print("❌ Error: SQLAlchemy required. Install with: pip install sqlalchemy")
    raise

load_dotenv()

# Database Configuration
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "fortress_db")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
ADMIN_USER = os.getenv("ADMIN_DB_USER", "miner_bot")
ADMIN_PASS = os.getenv("ADMIN_DB_PASS", "190AntiochCemeteryRD!!!")

# Spark-1 (Ollama) Configuration
WORKER_IP = "192.168.0.104"
OLLAMA_API = f"http://{WORKER_IP}:11434/api/generate"
MODEL = "mistral:latest"
API_TIMEOUT = 30

# SQLAlchemy Setup
DATABASE_URL = f"postgresql://{ADMIN_USER}:{ADMIN_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# Enums
class AssetClass(enum.Enum):
    """Asset class enumeration."""
    STOCK = "STOCK"
    CRYPTO = "CRYPTO"
    BOND = "BOND"
    COMMODITY = "COMMODITY"
    FOREX = "FOREX"
    OPTION = "OPTION"
    OTHER = "OTHER"


class Priority(enum.Enum):
    """Legal priority enumeration."""
    CRITICAL = "CRITICAL"  # Immediate action required
    HIGH = "HIGH"  # Urgent, within days
    MEDIUM = "MEDIUM"  # Standard processing
    LOW = "LOW"  # Routine
    ARCHIVE = "ARCHIVE"  # Historical only


# Updated Models
class MarketIntel(Base):
    """Stock market intelligence with ticker and asset_class."""
    __tablename__ = 'market_intel'
    
    id = Column(Integer, primary_key=True)
    ticker = Column(String(10), nullable=True)  # e.g., 'NVDA', 'BTC'
    asset_class = Column(String(50), nullable=True)  # e.g., 'STOCK', 'CRYPTO'
    broker = Column(String(255), nullable=True)
    action = Column(String(50), nullable=True)  # BUY, SELL, HOLD, etc.
    price = Column(Numeric(15, 4), nullable=True)
    source_email_id = Column(Integer, nullable=True)
    content = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    enriched_at = Column(DateTime, nullable=True)  # Track when enrichment completed


class LegalIntel(Base):
    """Legal cases with priority and next_deadline."""
    __tablename__ = 'legal_intel'
    
    id = Column(Integer, primary_key=True)
    case_name = Column(String(255), nullable=True)
    case_number = Column(String(100), nullable=True)
    court = Column(String(255), nullable=True)
    status = Column(String(100), nullable=True)
    priority = Column(String(50), nullable=True)  # CRITICAL, HIGH, MEDIUM, LOW, ARCHIVE
    next_deadline = Column(Date, nullable=True)  # Next important date
    source_email_id = Column(Integer, nullable=True)
    content = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    enriched_at = Column(DateTime, nullable=True)  # Track when enrichment completed


def call_llm(prompt: str) -> Optional[Dict[str, Any]]:
    """
    Call Spark-1 Ollama LLM API with structured JSON output.
    
    Args:
        prompt: Prompt to send to LLM
        
    Returns:
        Parsed JSON response or None on error
    """
    try:
        response = requests.post(
            OLLAMA_API,
            json={
                "model": MODEL,
                "prompt": prompt,
                "format": "json",
                "stream": False
            },
            timeout=API_TIMEOUT
        )
        
        if response.status_code != 200:
            print(f"   ❌ LLM API error: {response.status_code}")
            return None
        
        response_data = response.json()
        response_text = response_data.get("response", "").strip()
        
        if not response_text:
            return None
        
        # Clean JSON response (remove markdown if present)
        if response_text.startswith('```json'):
            response_text = response_text[7:]
        if response_text.startswith('```'):
            response_text = response_text[3:]
        if response_text.endswith('```'):
            response_text = response_text[:-3]
        response_text = response_text.strip()
        
        # Parse JSON
        try:
            data = json.loads(response_text)
            return data
        except json.JSONDecodeError as e:
            print(f"   ⚠️  JSON parsing error: {e}")
            return None
            
    except requests.exceptions.Timeout:
        print(f"   ❌ LLM API timeout after {API_TIMEOUT} seconds")
        return None
    except requests.exceptions.ConnectionError:
        print(f"   ❌ Connection error: Cannot reach Spark-1 at {WORKER_IP}")
        return None
    except Exception as e:
        print(f"   ❌ LLM API error: {e}")
        return None


def enrich_market_intel(record_id: int) -> Dict[str, Any]:
    """
    Enrich market_intel record using LLM to extract ticker and asset_class.
    
    Args:
        record_id: ID of market_intel record to enrich
        
    Returns:
        Dictionary with enrichment result:
            - 'success': Boolean
            - 'ticker': Extracted ticker symbol
            - 'asset_class': Extracted asset class
            - 'error': Error message if failed
    """
    session = SessionLocal()
    result = {
        'success': False,
        'ticker': None,
        'asset_class': None,
        'error': None
    }
    
    try:
        # Fetch record
        record = session.query(MarketIntel).filter_by(id=record_id).first()
        
        if not record:
            result['error'] = f'Record {record_id} not found'
            return result
        
        if not record.content:
            result['error'] = 'No content to analyze'
            return result
        
        # Skip if already enriched
        if record.ticker and record.asset_class:
            result['success'] = True
            result['ticker'] = record.ticker
            result['asset_class'] = record.asset_class
            return result
        
        # Prepare prompt for LLM
        truncated_content = record.content[:4000]  # Limit content length
        prompt = f"""Analyze this market intelligence content and extract structured data.

CONTENT:
{truncated_content}

Extract the following information:
1. Ticker Symbol: The trading symbol (e.g., 'NVDA', 'BTC', 'AAPL', 'ETH', 'TSLA')
   - For stocks: Use standard ticker symbols (1-5 uppercase letters)
   - For crypto: Use standard symbols (BTC, ETH, etc.)
   - Return null if no ticker found

2. Asset Class: Classify the asset type
   - Options: STOCK, CRYPTO, BOND, COMMODITY, FOREX, OPTION, OTHER
   - Use context clues (crypto exchanges, stock exchanges, etc.)

Return JSON format:
{{
    "ticker": "NVDA" or null,
    "asset_class": "STOCK" or "CRYPTO" or "BOND" or "COMMODITY" or "FOREX" or "OPTION" or "OTHER" or null
}}

Return ONLY valid JSON, no explanation."""

        print(f"   ⚡ Enriching market_intel #{record_id} with LLM...")
        llm_response = call_llm(prompt)
        
        if not llm_response:
            result['error'] = 'LLM API call failed'
            return result
        
        # Extract values
        ticker = llm_response.get('ticker')
        asset_class = llm_response.get('asset_class')
        
        # Normalize ticker (uppercase, strip)
        if ticker:
            ticker = str(ticker).upper().strip()[:10]
            if len(ticker) == 0:
                ticker = None
        
        # Normalize asset_class (uppercase, validate)
        valid_asset_classes = ['STOCK', 'CRYPTO', 'BOND', 'COMMODITY', 'FOREX', 'OPTION', 'OTHER']
        if asset_class:
            asset_class = str(asset_class).upper().strip()
            if asset_class not in valid_asset_classes:
                asset_class = 'OTHER'
        else:
            asset_class = None
        
        # Update record
        if ticker:
            record.ticker = ticker
        if asset_class:
            record.asset_class = asset_class
        
        record.enriched_at = datetime.utcnow()
        
        session.commit()
        
        result['success'] = True
        result['ticker'] = ticker
        result['asset_class'] = asset_class
        
        print(f"   ✅ Enriched: ticker={ticker}, asset_class={asset_class}")
        
    except Exception as e:
        session.rollback()
        result['error'] = f'Enrichment error: {str(e)}'
        print(f"   ❌ Enrichment failed: {e}")
        
    finally:
        session.close()
    
    return result


def enrich_legal_intel(record_id: int) -> Dict[str, Any]:
    """
    Enrich legal_intel record using LLM to extract priority and next_deadline.
    
    Args:
        record_id: ID of legal_intel record to enrich
        
    Returns:
        Dictionary with enrichment result:
            - 'success': Boolean
            - 'priority': Extracted priority level
            - 'next_deadline': Extracted deadline date (YYYY-MM-DD format)
            - 'error': Error message if failed
    """
    session = SessionLocal()
    result = {
        'success': False,
        'priority': None,
        'next_deadline': None,
        'error': None
    }
    
    try:
        # Fetch record
        record = session.query(LegalIntel).filter_by(id=record_id).first()
        
        if not record:
            result['error'] = f'Record {record_id} not found'
            return result
        
        if not record.content:
            result['error'] = 'No content to analyze'
            return result
        
        # Skip if already enriched
        if record.priority and record.next_deadline:
            result['success'] = True
            result['priority'] = record.priority
            result['next_deadline'] = record.next_deadline.isoformat() if record.next_deadline else None
            return result
        
        # Prepare prompt for LLM
        truncated_content = record.content[:4000]
        prompt = f"""Analyze this legal document and extract urgency information.

CONTENT:
{truncated_content}

Extract:
1. Priority Level: Assess urgency based on deadlines, legal requirements, and language
   - CRITICAL: Immediate action required (e.g., "must respond within 24 hours", "court date tomorrow")
   - HIGH: Urgent, within days (e.g., "response due by [date within 7 days]", "hearing next week")
   - MEDIUM: Standard processing (e.g., "response due in 30 days", routine filings)
   - LOW: Routine, no immediate urgency
   - ARCHIVE: Historical only, no action needed

2. Next Deadline: The most important upcoming date in YYYY-MM-DD format
   - Look for: court dates, filing deadlines, response dates, hearing dates
   - Return null if no clear deadline found

Consider these urgency indicators:
- Language: "urgent", "immediately", "as soon as possible", "time-sensitive"
- Timeframes: "within 24 hours", "by [date]", "due [date]"
- Legal actions: "default judgment", "hearing scheduled", "response required"

Return JSON format:
{{
    "priority": "CRITICAL" or "HIGH" or "MEDIUM" or "LOW" or "ARCHIVE" or null,
    "next_deadline": "YYYY-MM-DD" or null
}}

Return ONLY valid JSON, no explanation."""

        print(f"   ⚡ Enriching legal_intel #{record_id} with LLM...")
        llm_response = call_llm(prompt)
        
        if not llm_response:
            result['error'] = 'LLM API call failed'
            return result
        
        # Extract values
        priority = llm_response.get('priority')
        next_deadline_str = llm_response.get('next_deadline')
        
        # Normalize priority (uppercase, validate)
        valid_priorities = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'ARCHIVE']
        if priority:
            priority = str(priority).upper().strip()
            if priority not in valid_priorities:
                priority = 'MEDIUM'  # Default to medium if invalid
        else:
            priority = 'MEDIUM'  # Default if not found
        
        # Parse deadline date
        next_deadline = None
        if next_deadline_str:
            try:
                # Try to parse the date
                if isinstance(next_deadline_str, str):
                    next_deadline = datetime.strptime(next_deadline_str, '%Y-%m-%d').date()
                elif isinstance(next_deadline_str, datetime):
                    next_deadline = next_deadline_str.date()
            except (ValueError, TypeError):
                # Try alternative date parsing
                try:
                    # Look for dates in common formats
                    date_patterns = [
                        r'\b(\d{4}-\d{2}-\d{2})\b',  # YYYY-MM-DD
                        r'\b(\d{1,2}/\d{1,2}/\d{4})\b',  # MM/DD/YYYY
                        r'\b(\d{1,2}-\d{1,2}-\d{4})\b',  # MM-DD-YYYY
                    ]
                    content_lower = record.content.lower()
                    for pattern in date_patterns:
                        matches = re.findall(pattern, content_lower)
                        if matches:
                            # Use first match as deadline
                            break
                    next_deadline = None  # Could add more sophisticated parsing
                except:
                    next_deadline = None
        
        # Update record
        record.priority = priority
        if next_deadline:
            record.next_deadline = next_deadline
        
        record.enriched_at = datetime.utcnow()
        
        session.commit()
        
        result['success'] = True
        result['priority'] = priority
        result['next_deadline'] = next_deadline.isoformat() if next_deadline else None
        
        print(f"   ✅ Enriched: priority={priority}, next_deadline={result['next_deadline']}")
        
    except Exception as e:
        session.rollback()
        result['error'] = f'Enrichment error: {str(e)}'
        print(f"   ❌ Enrichment failed: {e}")
        
    finally:
        session.close()
    
    return result


def process_pending_enrichments(batch_size: int = 10) -> Dict[str, int]:
    """
    Process pending enrichments for market_intel and legal_intel.
    This function finds records without enrichment and processes them.
    
    Args:
        batch_size: Number of records to process per batch
        
    Returns:
        Dictionary with processing statistics
    """
    session = SessionLocal()
    stats = {
        'market_processed': 0,
        'market_errors': 0,
        'legal_processed': 0,
        'legal_errors': 0
    }
    
    try:
        # Process market_intel records without ticker/asset_class
        market_records = session.query(MarketIntel).filter(
            (MarketIntel.ticker == None) | (MarketIntel.asset_class == None),
            MarketIntel.content.isnot(None)
        ).limit(batch_size).all()
        
        print(f"\n📈 Processing {len(market_records)} market_intel records...")
        for record in market_records:
            result = enrich_market_intel(record.id)
            if result['success']:
                stats['market_processed'] += 1
            else:
                stats['market_errors'] += 1
        
        # Process legal_intel records without priority/next_deadline
        legal_records = session.query(LegalIntel).filter(
            (LegalIntel.priority == None) | (LegalIntel.next_deadline == None),
            LegalIntel.content.isnot(None)
        ).limit(batch_size).all()
        
        print(f"\n⚖️  Processing {len(legal_records)} legal_intel records...")
        for record in legal_records:
            result = enrich_legal_intel(record.id)
            if result['success']:
                stats['legal_processed'] += 1
            else:
                stats['legal_errors'] += 1
        
    finally:
        session.close()
    
    return stats


if __name__ == "__main__":
    # Test the enrichment functions
    print("🛡️  FORTRESS PRIME - Enrichment Service Test")
    print("=" * 60)
    
    # Process pending enrichments
    stats = process_pending_enrichments(batch_size=5)
    
    print("\n" + "=" * 60)
    print("✅ ENRICHMENT COMPLETE")
    print("=" * 60)
    print(f"📊 Statistics:")
    print(f"   • Market Intel: {stats['market_processed']} enriched, {stats['market_errors']} errors")
    print(f"   • Legal Intel: {stats['legal_processed']} enriched, {stats['legal_errors']} errors")
