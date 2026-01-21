"""
🛡️ FORTRESS PRIME - Enterprise Text-to-SQL Engine
The Analyst Brain: Natural Language to SQL Query Converter
Role: Senior Hedge Fund Database Administrator
"""

import os
import re
import json
import psycopg2
import pandas as pd
import requests
from typing import Tuple, Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "fortress_db")
DB_PORT = os.getenv("DB_PORT", "5432")
ANALYST_USER = os.getenv("DB_USER", "analyst_reader")  # Uses DB_USER from .env
ANALYST_PASS = os.getenv("DB_PASSWORD", "6652201a")  # Uses DB_PASSWORD from .env

# Spark-1 (Ollama) Configuration
WORKER_IP = "192.168.0.104"
OLLAMA_API = f"http://{WORKER_IP}:11434/api/generate"
MODEL = "mistral:latest"
API_TIMEOUT = 30


def get_schema() -> str:
    """
    Step A: Get Context
    Query information_schema to get column names for finance_invoices and market_signals.
    
    Returns:
        Formatted schema string for prompting
    """
    try:
        # Use admin connection to query schema
        admin_conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            port=int(DB_PORT),
            user=os.getenv("ADMIN_DB_USER", "miner_bot"),
            password=os.getenv("ADMIN_DB_PASS", "190AntiochCemeteryRD!!!")
        )
        cur = admin_conn.cursor()
        
        schema_info = []
        
        # Get schema for finance_invoices
        cur.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'finance_invoices'
            ORDER BY ordinal_position
        """)
        
        finance_columns = cur.fetchall()
        if finance_columns:
            schema_info.append("Table: finance_invoices")
            for col_name, data_type, is_nullable in finance_columns:
                schema_info.append(f"  - {col_name} ({data_type}) {'NULL' if is_nullable == 'YES' else 'NOT NULL'}")
        
        # Get schema for market_signals
        cur.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'market_signals'
            ORDER BY ordinal_position
        """)
        
        market_columns = cur.fetchall()
        if market_columns:
            schema_info.append("\nTable: market_signals")
            for col_name, data_type, is_nullable in market_columns:
                schema_info.append(f"  - {col_name} ({data_type}) {'NULL' if is_nullable == 'YES' else 'NOT NULL'}")
        
        cur.close()
        admin_conn.close()
        
        return "\n".join(schema_info) if schema_info else "No schema information available"
        
    except Exception as e:
        return f"Error fetching schema: {str(e)}"


def extract_sql_from_response(response_text: str) -> Optional[str]:
    """
    Extract SQL query from Mistral response (looks for ```sql blocks).
    
    Args:
        response_text: Raw response from Mistral
        
    Returns:
        Extracted SQL query or None if not found
    """
    # Clean response
    response_text = response_text.strip()
    
    # Try to find SQL in code blocks
    sql_patterns = [
        r'```sql\s*(.*?)\s*```',  # ```sql ... ```
        r'```\s*(SELECT.*?)\s*```',  # ``` SELECT ... ```
        r'(SELECT.*?);',  # Direct SQL ending with semicolon
    ]
    
    for pattern in sql_patterns:
        match = re.search(pattern, response_text, re.DOTALL | re.IGNORECASE)
        if match:
            sql = match.group(1).strip()
            # Remove any leading/trailing markdown artifacts
            sql = sql.strip('`').strip()
            if sql.upper().startswith('SELECT'):
                return sql
    
    # If no pattern matched, try to find SELECT statement directly
    select_match = re.search(r'(SELECT.*?)(?:\n\n|\Z)', response_text, re.DOTALL | re.IGNORECASE)
    if select_match:
        sql = select_match.group(1).strip()
        if sql.upper().startswith('SELECT'):
            return sql
    
    return None


def generate_sql(question: str, schema: str) -> Optional[str]:
    """
    Step B: Prompting
    Send prompt to Spark-1 (Mistral) to generate SQL query.
    
    Args:
        question: User's natural language question
        schema: Database schema context
        
    Returns:
        Generated SQL query or None on error
    """
    prompt = f"""You are a Senior Hedge Fund Database Administrator. Generate a PostgreSQL query to answer this question.

DATABASE SCHEMA:
{schema}

USER QUESTION:
{question}

INSTRUCTIONS:
- Write ONLY the SQL query inside ```sql blocks.
- Do not explain yet.
- Use proper PostgreSQL syntax.
- Only query tables: finance_invoices and market_signals.
- Return clean, executable SQL."""

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
            print(f"❌ API error: {response.status_code}")
            return None
        
        response_data = response.json()
        response_text = response_data.get("response", "")
        
        if not response_text:
            return None
        
        # Extract SQL from response
        sql = extract_sql_from_response(response_text)
        return sql
        
    except requests.exceptions.Timeout:
        print(f"❌ API timeout after {API_TIMEOUT} seconds")
        return None
    except requests.exceptions.ConnectionError:
        print(f"❌ Connection error: Cannot reach Spark-1 at {WORKER_IP}")
        return None
    except Exception as e:
        print(f"❌ Error generating SQL: {e}")
        return None


def execute_query(sql: str) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """
    Step C: Execution (The Guardrail)
    Execute SQL query using read-only connection.
    
    Args:
        sql: SQL query to execute
        
    Returns:
        Tuple of (DataFrame, error_message). One will be None.
    """
    try:
        # Connect as analyst_reader (Read-Only)
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            port=int(DB_PORT),
            user=ANALYST_USER,
            password=ANALYST_PASS
        )
        
        # Execute query using pandas
        df = pd.read_sql(sql, conn)
        conn.close()
        
        return df, None
        
    except psycopg2.OperationalError as e:
        # Connection/auth error
        error_msg = f"Database connection error: {str(e)}"
        return None, error_msg
    except psycopg2.ProgrammingError as e:
        # SQL syntax error
        error_msg = f"SQL error: {str(e)}"
        return None, error_msg
    except Exception as e:
        # Other errors
        error_msg = f"Execution error: {str(e)}"
        return None, error_msg


def synthesize_summary(df: pd.DataFrame) -> str:
    """
    Step D: Synthesis
    Send dataframe to Mistral for natural language summary.
    
    Args:
        df: Result dataframe
        
    Returns:
        Natural language summary sentence
    """
    # Prepare data summary
    first_5_rows = df.head(5).to_string() if len(df) > 0 else "No rows"
    summary_stats = f"Total rows: {len(df)}, Columns: {', '.join(df.columns.tolist())}"
    
    # Get numeric summary if applicable
    numeric_summary = ""
    numeric_cols = df.select_dtypes(include=['number']).columns
    if len(numeric_cols) > 0:
        numeric_summary = df[numeric_cols].describe().to_string()
    
    prompt = f"""You are a Senior Hedge Fund Database Administrator. Summarize this financial data in 1 sentence for a Portfolio Manager.

DATA SAMPLE (First 5 rows):
{first_5_rows}

SUMMARY STATISTICS:
{summary_stats}

NUMERIC SUMMARY:
{numeric_summary}

Write a concise, professional 1-sentence summary suitable for a Portfolio Manager."""

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
            return "Summary generation failed."
        
        response_data = response.json()
        summary = response_data.get("response", "").strip()
        
        # Clean up summary (remove quotes, extra whitespace)
        summary = re.sub(r'^["\']|["\']$', '', summary)
        summary = summary.strip()
        
        return summary if summary else "Data retrieved successfully."
        
    except Exception as e:
        return f"Summary generation error: {str(e)}"


class FinancialAnalyst:
    """
    Enterprise Text-to-SQL Engine
    Converts natural language questions to SQL queries and provides summaries.
    """
    
    def __init__(self):
        """Initialize the Financial Analyst."""
        self.schema = None
        self._load_schema()
    
    def _load_schema(self):
        """Load database schema on initialization."""
        self.schema = get_schema()
        if not self.schema or "Error" in self.schema:
            print(f"⚠️  Warning: Could not load schema: {self.schema}")
    
    def ask(self, question: str) -> Tuple[pd.DataFrame, str, Optional[str]]:
        """
        Main interface: Ask a natural language question and get SQL results + summary.
        
        Args:
            question: Natural language question about the financial data
            
        Returns:
            Tuple of (DataFrame with results, summary_text, sql_query)
            If error occurs, DataFrame will be empty and summary_text will contain error message
        """
        print(f"📊 Analyst Brain: Processing question...")
        print(f"   Q: {question}")
        
        # Step A: Get Context (if not already loaded)
        if not self.schema:
            print("   🔄 Loading database schema...")
            self.schema = get_schema()
        
        # Step B: Generate SQL
        print("   ⚡ Generating SQL query (Spark-1)...")
        sql = generate_sql(question, self.schema)
        
        if not sql:
            error_df = pd.DataFrame()
            error_msg = "Failed to generate SQL query. Please rephrase your question."
            return error_df, error_msg, None
        
        print(f"   ✅ SQL Generated:\n   {sql[:200]}...")
        
        # Step C: Execute Query
        print("   🔍 Executing query (Read-Only)...")
        df, error = execute_query(sql)
        
        if error:
            error_df = pd.DataFrame()
            return error_df, error, sql  # Return SQL even on error for debugging
        
        if df.empty:
            empty_df = pd.DataFrame()
            return empty_df, "Query executed successfully but returned no results.", sql
        
        print(f"   ✅ Query returned {len(df)} rows")
        
        # Step D: Synthesize Summary
        print("   📝 Generating summary (Spark-1)...")
        summary = synthesize_summary(df)
        
        return df, summary, sql


# CLI Interface
if __name__ == "__main__":
    import sys
    
    print("🛡️  FORTRESS PRIME - Enterprise Text-to-SQL Engine")
    print("=" * 60)
    print("Role: Senior Hedge Fund Database Administrator")
    print("=" * 60)
    
    analyst = FinancialAnalyst()
    
    if len(sys.argv) > 1:
        # Command line question
        question = " ".join(sys.argv[1:])
        df, summary, sql = analyst.ask(question)
        
        print("\n" + "=" * 60)
        print("📊 RESULTS")
        print("=" * 60)
        print(f"\n📈 Summary: {summary}\n")
        if sql:
            print(f"🔍 SQL Query:\n{sql}\n")
        print("📋 Data:")
        print(df.to_string())
        
    else:
        # Interactive mode
        print("\n💬 Interactive Mode (Type 'exit' to quit)\n")
        
        while True:
            try:
                question = input("Ask: ").strip()
                
                if question.lower() in ['exit', 'quit', 'q']:
                    print("👋 Exiting...")
                    break
                
                if not question:
                    continue
                
                df, summary, sql = analyst.ask(question)
                
                print("\n" + "=" * 60)
                print("📊 RESULTS")
                print("=" * 60)
                print(f"\n📈 Summary: {summary}\n")
                if sql:
                    print(f"🔍 SQL Query:\n{sql}\n")
                
                if not df.empty:
                    print("📋 Data (showing first 10 rows):")
                    print(df.head(10).to_string())
                    if len(df) > 10:
                        print(f"\n... and {len(df) - 10} more rows")
                else:
                    print("📋 No data returned.")
                
                print("\n" + "-" * 60 + "\n")
                
            except KeyboardInterrupt:
                print("\n👋 Exiting...")
                break
            except Exception as e:
                print(f"\n❌ Error: {e}\n")
