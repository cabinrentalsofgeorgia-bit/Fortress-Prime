"""
🛡️ FORTRESS PRIME - Data Router
Intelligent routing of email content to appropriate database tables based on sender/subject analysis.
Uses SQLAlchemy for database operations.
"""

import os
import re
from typing import Optional, Dict, Any
from datetime import datetime
from dotenv import load_dotenv

_MINER_BOT_PASSWORD = os.getenv("MINER_BOT_DB_PASSWORD")
if not _MINER_BOT_PASSWORD:
    raise RuntimeError("MINER_BOT_DB_PASSWORD env var required")


load_dotenv()

try:
    from sqlalchemy import create_engine, Column, Integer, String, Numeric, Date, Text, DateTime, CheckConstraint
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.exc import IntegrityError
except ImportError:
    print("❌ Error: SQLAlchemy required. Install with: pip install sqlalchemy")
    raise

# Database Configuration
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "fortress_db")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
ADMIN_USER = os.getenv("ADMIN_DB_USER", "miner_bot")
ADMIN_PASS = os.getenv("ADMIN_DB_PASS", _MINER_BOT_PASSWORD)

# SQLAlchemy Setup
DATABASE_URL = f"postgresql://{ADMIN_USER}:{ADMIN_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# SQLAlchemy Models
class FinanceInvoice(Base):
    """Expenses table with $50k safety valve."""
    __tablename__ = 'finance_invoices'
    
    id = Column(Integer, primary_key=True)
    vendor = Column(String(255), nullable=False)
    amount = Column(Numeric(15, 2), nullable=False)
    date = Column(Date, nullable=False)
    category = Column(String(100), nullable=True)
    source_email_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Safety valve: Prevent amounts >= $50,000
    __table_args__ = (
        CheckConstraint('amount < 50000', name='check_sane_amount'),
    )


class RealEstateIntel(Base):
    """Property values and real estate intelligence."""
    __tablename__ = 'real_estate_intel'
    
    id = Column(Integer, primary_key=True)
    property_name = Column(String(255), nullable=True)
    property_value = Column(Numeric(15, 2), nullable=True)
    property_address = Column(Text, nullable=True)
    zillow_estimate = Column(Numeric(15, 2), nullable=True)
    date = Column(Date, nullable=True)
    source_email_id = Column(Integer, nullable=True)
    raw_content = Column(Text, nullable=True)  # Store full email content
    created_at = Column(DateTime, default=datetime.utcnow)


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


def analyze_email_context(sender: str, subject: str, content: str) -> str:
    """
    Analyze email to determine routing destination.
    
    Args:
        sender: Email sender address
        subject: Email subject line
        content: Email body content
        
    Returns:
        Route destination: 'real_estate', 'finance', 'market', 'legal', or None
    """
    sender_lower = (sender or "").lower()
    subject_lower = (subject or "").lower()
    content_lower = (content or "").lower()
    
    # Route 1: Zillow → Real Estate
    zillow_keywords = ['zillow', 'zestimate', 'property value', 'home value', 'estimate']
    if any(keyword in sender_lower for keyword in ['zillow']):
        return 'real_estate'
    if any(keyword in subject_lower or keyword in content_lower for keyword in zillow_keywords):
        return 'real_estate'
    
    # Route 2: Broker → Market Intel
    broker_keywords = ['broker', 'trader', 'trading', 'schwab', 'fidelity', 'td ameritrade', 
                       'etrade', 'robinhood', 'trade confirmation', 'order filled', 
                       'dividend', 'ticker', 'symbol']
    if any(keyword in sender_lower or keyword in subject_lower or keyword in content_lower 
           for keyword in broker_keywords):
        return 'market'
    
    # Route 3: Bills/Invoices → Finance (but only if < $50k)
    invoice_keywords = ['invoice', 'bill', 'payment', 'receipt', 'statement', 'billing', 
                        'amount due', 'total', 'charge']
    if any(keyword in subject_lower or keyword in content_lower for keyword in invoice_keywords):
        # Check if it's a legal document (might have invoice keywords but should go to legal)
        legal_keywords = ['lawsuit', 'court', 'legal', 'attorney', 'lawyer', 'case number']
        if not any(keyword in content_lower for keyword in legal_keywords):
            return 'finance'
    
    # Route 4: Legal → Legal Intel
    legal_keywords = ['lawsuit', 'court', 'legal notice', 'attorney', 'lawyer', 
                      'case number', 'complaint', 'filing', 'subpoena']
    if any(keyword in sender_lower or keyword in subject_lower or keyword in content_lower 
           for keyword in legal_keywords):
        return 'legal'
    
    # Default: No routing (return None)
    return None


def extract_amount(text: str) -> Optional[float]:
    """
    Extract monetary amount from text.
    
    Args:
        text: Text to search for amount
        
    Returns:
        Extracted amount as float, or None if not found
    """
    # Pattern: $123,456.78 or 123456.78
    pattern = r'\$?([\d,]+\.?\d{0,2})'
    matches = re.findall(pattern, text)
    
    if matches:
        # Get the largest match (likely the total amount)
        amounts = []
        for match in matches:
            # Remove commas and convert
            clean_match = match.replace(',', '')
            try:
                amount = float(clean_match)
                # Filter out unreasonable amounts (likely not currency)
                if 0 < amount < 10000000:  # Between $0 and $10M
                    amounts.append(amount)
            except ValueError:
                continue
        
        if amounts:
            # Return the largest amount found
            return max(amounts)
    
    return None


def route_incoming_data(email_content: Dict[str, Any], source_email_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Main router function: Analyze email and route to appropriate table.
    
    Args:
        email_content: Dictionary with keys:
            - 'sender': Email sender address
            - 'subject': Email subject line
            - 'content': Email body content
            - 'date': Optional date (defaults to today)
        source_email_id: Optional ID from email_archive table
        
    Returns:
        Dictionary with routing result:
            - 'route': Destination table name ('real_estate_intel', 'finance_invoices', etc.)
            - 'success': Boolean indicating if insert succeeded
            - 'error': Error message if failed
            - 'record_id': ID of inserted record if successful
    """
    sender = email_content.get('sender', '')
    subject = email_content.get('subject', '')
    content = email_content.get('content', '')
    date = email_content.get('date')
    
    if not date:
        date = datetime.now().date()
    elif isinstance(date, str):
        try:
            date = datetime.strptime(date, '%Y-%m-%d').date()
        except ValueError:
            date = datetime.now().date()
    elif isinstance(date, datetime):
        date = date.date()
    
    # Determine route
    route = analyze_email_context(sender, subject, content)
    
    if not route:
        return {
            'route': None,
            'success': False,
            'error': 'No matching route found for this email',
            'record_id': None
        }
    
    session = SessionLocal()
    result = {
        'route': route,
        'success': False,
        'error': None,
        'record_id': None
    }
    
    try:
        if route == 'real_estate':
            # Route to real_estate_intel
            # Extract property value from content
            property_value = extract_amount(content)
            
            # Try to extract property name/address from subject or content
            property_name = None
            if 'property' in subject.lower() or 'home' in subject.lower():
                property_name = subject
            
            record = RealEstateIntel(
                property_name=property_name,
                property_value=property_value,
                zillow_estimate=property_value,  # If from Zillow, this is the estimate
                date=date,
                source_email_id=source_email_id,
                raw_content=content[:5000] if content else None  # Store first 5000 chars
            )
            session.add(record)
            session.commit()
            result['success'] = True
            result['record_id'] = record.id
            
        elif route == 'finance':
            # Route to finance_invoices (with $50k safety valve)
            amount = extract_amount(content)
            
            if not amount:
                result['error'] = 'No valid amount found in email content'
                session.rollback()
                return result
            
            # Safety valve: Check amount < $50k
            if amount >= 50000:
                result['error'] = f'Amount ${amount:,.2f} exceeds $50,000 limit. Requires manual review.'
                session.rollback()
                return result
            
            # Extract vendor from sender or subject
            vendor = sender.split('@')[0] if '@' in sender else sender
            if not vendor or len(vendor) > 255:
                vendor = subject[:100] if subject else 'Unknown Vendor'
            
            try:
                record = FinanceInvoice(
                    vendor=vendor,
                    amount=amount,
                    date=date,
                    category=None,  # Can be set later
                    source_email_id=source_email_id
                )
                session.add(record)
                session.commit()
                result['success'] = True
                result['record_id'] = record.id
            except IntegrityError as e:
                # This catches the CHECK constraint violation
                if 'check_sane_amount' in str(e):
                    result['error'] = f'Safety valve triggered: Amount ${amount:,.2f} exceeds $50,000 limit'
                else:
                    result['error'] = f'Database constraint violation: {str(e)}'
                session.rollback()
                return result
                
        elif route == 'market':
            # Route to market_intel
            # Extract ticker, action, price from content
            ticker_match = re.search(r'\b([A-Z]{1,5})\b', content[:500])
            ticker = ticker_match.group(1) if ticker_match else None
            
            action = None
            if any(word in content.lower() for word in ['buy', 'purchase', 'acquired']):
                action = 'BUY'
            elif any(word in content.lower() for word in ['sell', 'sold', 'sale']):
                action = 'SELL'
            elif any(word in content.lower() for word in ['dividend', 'distribution']):
                action = 'DIVIDEND'
            
            price = extract_amount(content)
            
            # Extract broker from sender
            broker = sender.split('@')[0] if '@' in sender else sender
            
            record = MarketIntel(
                ticker=ticker,  # Will be enriched by LLM if None
                asset_class=None,  # Will be enriched by LLM
                broker=broker,
                action=action,
                price=price,
                source_email_id=source_email_id,
                content=content[:5000] if content else None
            )
            session.add(record)
            session.commit()
            result['success'] = True
            result['record_id'] = record.id
            
            # Trigger automatic enrichment (async - don't block)
            try:
                from enrichment_service import enrich_market_intel
                enrich_market_intel(record.id)  # Enrich immediately
            except Exception as e:
                print(f"   ⚠️  Auto-enrichment failed (will retry later): {e}")
            
        elif route == 'legal':
            # Route to legal_intel
            # Extract case number, court, etc. from content
            case_number_match = re.search(r'case\s*(?:number|#)?\s*:?\s*([A-Z0-9-]+)', content, re.IGNORECASE)
            case_number = case_number_match.group(1) if case_number_match else None
            
            court_match = re.search(r'(?:court|district|county)\s+of\s+([A-Za-z\s]+)', content, re.IGNORECASE)
            court = court_match.group(1).strip() if court_match else None
            
            record = LegalIntel(
                case_name=subject if subject else None,
                case_number=case_number,
                court=court,
                status=None,  # Can be extracted with more sophisticated parsing
                priority=None,  # Will be enriched by LLM
                next_deadline=None,  # Will be enriched by LLM
                source_email_id=source_email_id,
                content=content[:5000] if content else None
            )
            session.add(record)
            session.commit()
            result['success'] = True
            result['record_id'] = record.id
            
            # Trigger automatic enrichment (async - don't block)
            try:
                from enrichment_service import enrich_legal_intel
                enrich_legal_intel(record.id)  # Enrich immediately
            except Exception as e:
                print(f"   ⚠️  Auto-enrichment failed (will retry later): {e}")
            
    except Exception as e:
        session.rollback()
        result['error'] = f'Unexpected error during routing: {str(e)}'
        
    finally:
        session.close()
    
    return result


# Create tables if they don't exist (run once)
def create_tables():
    """Create all tables if they don't exist."""
    Base.metadata.create_all(engine)
    print("✅ Database tables verified/created")


if __name__ == "__main__":
    # Test the router
    print("🛡️  FORTRESS PRIME - Data Router Test")
    print("=" * 60)
    
    create_tables()
    
    # Test case 1: Zillow email
    test_email_1 = {
        'sender': 'notifications@zillow.com',
        'subject': 'Your Home Value Estimate',
        'content': 'Your property at 123 Main St has an estimated value of $419,000.',
        'date': datetime.now().date()
    }
    
    result1 = route_incoming_data(test_email_1)
    print(f"\nTest 1 (Zillow): {result1}")
    
    # Test case 2: Invoice (under $50k)
    test_email_2 = {
        'sender': 'billing@utility.com',
        'subject': 'Invoice #12345',
        'content': 'Your invoice total is $150.00 due by end of month.',
        'date': datetime.now().date()
    }
    
    result2 = route_incoming_data(test_email_2)
    print(f"\nTest 2 (Invoice < $50k): {result2}")
    
    # Test case 3: Invoice (over $50k - should fail)
    test_email_3 = {
        'sender': 'billing@bigcompany.com',
        'subject': 'Invoice #99999',
        'content': 'Your invoice total is $75,000.00',
        'date': datetime.now().date()
    }
    
    result3 = route_incoming_data(test_email_3)
    print(f"\nTest 3 (Invoice > $50k): {result3}")
    
    print("\n✅ Router test complete!")
