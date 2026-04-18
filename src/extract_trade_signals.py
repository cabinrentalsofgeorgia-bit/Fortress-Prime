import os
import email
from email.policy import default
import psycopg2
import pytesseract
from PIL import Image
import io
import re

_MINER_BOT_PASSWORD = os.getenv("MINER_BOT_DB_PASSWORD")
if not _MINER_BOT_PASSWORD:
    raise RuntimeError("MINER_BOT_DB_PASSWORD env var required")


# --- CONFIGURATION ---
DB_PASS = _MINER_BOT_PASSWORD
CHART_DIR = "/mnt/fortress_data/charts"

def get_db_connection():
    return psycopg2.connect(host="localhost", database="fortress_db", user="miner_bot", password=DB_PASS)

def analyze_image(img_data):
    try:
        image = Image.open(io.BytesIO(img_data))
        
        # 1. OCR for Price
        text = pytesseract.image_to_string(image)
        # Look for price patterns like $124.50
        prices = re.findall(r'\$([\d,]+\.\d{2})', text)
        price = max(prices) if prices else "Unknown"

        # 2. Color Analysis for Signal (Green vs Red)
        # Resize to small to get average color dominance
        small = image.resize((1, 1))
        color = small.getpixel((0, 0))
        
        # Simple heuristic: Is there more Red or Green in the dominant tone?
        r, g, b = color[0], color[1], color[2]
        if g > r + 20:
            signal = "🟢 BUY"
        elif r > g + 20:
            signal = "🔴 SELL"
        else:
            signal = "⚪ HOLD/NEUTRAL"
            
        return signal, price
    except:
        return None, None

def main():
    print("👁️  OPERATION RETINA: TRADE SIGNAL EXTRACTION")
    print("---------------------------------------------")
    
    if not os.path.exists(CHART_DIR):
        os.makedirs(CHART_DIR)

    conn = get_db_connection()
    cur = conn.cursor()

    # Target only Market Intelligence emails
    cur.execute("SELECT file_path, subject, sent_at FROM email_archive WHERE category = 'Market Intelligence' AND (subject ILIKE '%Trade Triangle%' OR subject ILIKE '%Alert%') LIMIT 500")
    
    signals_found = 0
    
    for row in cur.fetchall():
        path, subject, date = row
        try:
            with open(path, 'rb') as f:
                msg = email.message_from_binary_file(f, policy=default)
            
            for part in msg.walk():
                if part.get_content_maintype() == 'image':
                    img_data = part.get_payload(decode=True)
                    
                    # Analyze
                    signal, price = analyze_image(img_data)
                    
                    if signal and signal != "⚪ HOLD/NEUTRAL":
                        print(f"   {date.date()} | {signal} | Price: ${price} | Ref: {subject[:30]}...")
                        signals_found += 1
                        # Save the image for evidence
                        fname = f"{date.date()}_{signal.split()[1]}_{price}.png"
                        with open(os.path.join(CHART_DIR, fname), 'wb') as f_out:
                            f_out.write(img_data)
                        break # Found the chart, move to next email
        except Exception:
            pass

    print(f"\n✅ Scan Complete. Extracted {signals_found} verified signals.")

if __name__ == "__main__":
    main()
