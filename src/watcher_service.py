import os
import shutil
import time
import psycopg2
import requests
import pypdf
import re
import logging
from datetime import datetime

# --- ENTERPRISE CONFIGURATION ---
# "Hot Data" Input - Files here will be ingested AND MOVED.
WATCH_FOLDER = "/mnt/fortress_data/market_input"
# Where finished files go (Inside the same share)
PROCESSED_FOLDER = "/mnt/fortress_data/market_input/Processed"

# Database & AI Credentials
DB_PASS = os.getenv("DB_PASS", os.getenv("ADMIN_DB_PASS", ""))
OLLAMA_API_URL = "http://localhost:11434/api"
LOG_FILE = "/home/admin/fortress-prime/logs/watcher.log"

# Setup Logging (Writes to file and console)
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

def get_db_connection():
    return psycopg2.connect(host="localhost", database="fortress_db", user="miner_bot", password=DB_PASS)

def get_embedding(text):
    try:
        # 60s timeout for stability on large PDF chunks
        response = requests.post(
            f"{OLLAMA_API_URL}/embeddings", 
            json={"model": "nomic-embed-text", "prompt": text}, 
            timeout=60
        )
        if response.status_code == 200:
            return response.json().get("embedding")
    except Exception as e:
        logging.error(f"Embedding API Error: {e}")
    return None

def extract_market_signals(text):
    """
    EXTRACTOR ENGINE:
    Captures Market Club "Score: +100", "75 Sell", etc.
    """
    signal_strength = None
    signal_direction = None
    
    # PATTERN 1: Explicit Score (e.g., "Chart Score: +100", "Score: -75")
    score_match = re.search(r'(?:Score|Chart Analysis|Smart Scan)\s*:?\s*([+-]?\d+)', text, re.IGNORECASE)
    if score_match:
        try:
            signal_strength = int(score_match.group(1))
            if signal_strength >= 70: signal_direction = "BUY"
            elif signal_strength <= -70: signal_direction = "SELL"
            else: signal_direction = "NEUTRAL"
        except:
            pass

    # PATTERN 2: Text-based signals (e.g., "Trade Triangles: Buy") if no score found
    if not signal_direction:
        lower_text = text.lower()
        if "strong buy" in lower_text or "score 100 buy" in lower_text:
            signal_direction = "BUY"
            signal_strength = 100
        elif "strong sell" in lower_text or "score 100 sell" in lower_text:
            signal_direction = "SELL"
            signal_strength = -100

    return signal_strength, signal_direction

def process_file(filename):
    file_path = os.path.join(WATCH_FOLDER, filename)
    logging.info(f"⚡ Detecting file: {filename}")
    
    text_content = ""
    try:
        # 1. READ FILE
        if filename.lower().endswith(".pdf"):
            reader = pypdf.PdfReader(file_path)
            for page in reader.pages:
                text_content += page.extract_text() + "\n"
        elif filename.lower().endswith((".txt", ".md", ".html")):
            with open(file_path, "r", encoding="utf-8", errors='ignore') as f:
                text_content = f.read()
        else:
            logging.warning(f"Skipping unsupported file: {filename}")
            return False

        if not text_content.strip():
            return False

        # 2. EXTRACT STRUCTURED DATA
        strength, direction = extract_market_signals(text_content)
        if strength is not None:
            logging.info(f"   -> 🎯 SIGNAL EXTRACTED: {direction} ({strength})")

        # 3. VECTORIZE & STORE
        CHUNK_SIZE = 4000
        chunks = [text_content[i:i+CHUNK_SIZE] for i in range(0, len(text_content), CHUNK_SIZE)]

        conn = get_db_connection()
        cur = conn.cursor()

        for i, chunk in enumerate(chunks):
            vector = get_embedding(chunk)
            if vector:
                # Insert with new structured columns
                cur.execute("""
                    INSERT INTO market_intel 
                    (source_file, content, embedding, sender, subject_line, sent_at, signal_strength, signal_direction)
                    VALUES (%s, %s, %s, %s, %s, NOW(), %s, %s)
                """, (
                    filename, 
                    chunk, 
                    vector, 
                    "NAS Watcher", 
                    f"{filename} (Part {i+1})",
                    strength if i == 0 else None, # Only tag the first chunk
                    direction if i == 0 else None
                ))
                conn.commit()
        
        conn.close()
        return True

    except Exception as e:
        logging.error(f"Processing Failed {filename}: {e}")
        return False

# --- SERVICE LOOP ---
if __name__ == "__main__":
    print(f"🛡️  Fortress Watcher Service Started")
    print(f"📂 Monitoring Tier 2 Storage: {WATCH_FOLDER}")
    
    # Ensure Folders Exist
    os.makedirs(WATCH_FOLDER, exist_ok=True)
    os.makedirs(PROCESSED_FOLDER, exist_ok=True)

    while True:
        try:
            files = [f for f in os.listdir(WATCH_FOLDER) if os.path.isfile(os.path.join(WATCH_FOLDER, f))]
            for filename in files:
                time.sleep(2) # Wait for write to finish
                success = process_file(filename)
                if success:
                    shutil.move(os.path.join(WATCH_FOLDER, filename), os.path.join(PROCESSED_FOLDER, filename))
                    logging.info(f"✅ Archived: {filename}")
        except Exception as e:
            logging.error(f"Loop Error: {e}")
            
        time.sleep(30)
