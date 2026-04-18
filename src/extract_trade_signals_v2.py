import psycopg2
import requests
import re
import os
from PIL import Image
import pytesseract
import io
from datetime import datetime

_MINER_BOT_PASSWORD = os.getenv("MINER_BOT_DB_PASSWORD")
if not _MINER_BOT_PASSWORD:
    raise RuntimeError("MINER_BOT_DB_PASSWORD env var required")


# --- CONFIGURATION ---
DB_PASS = _MINER_BOT_PASSWORD
CHART_DIR = "/mnt/fortress_data/charts"

def get_db_connection():
    return psycopg2.connect(host="localhost", database="fortress_db", user="miner_bot", password=DB_PASS)

def analyze_image(img_bytes, date_str):
    try:
        image = Image.open(io.BytesIO(img_bytes))
        
        # 1. Color Analysis (Green vs Red Triangle)
        small = image.resize((1, 1))
        color = small.getpixel((0, 0))
        r, g, b = color[0], color[1], color[2]
        
        signal = None
        if g > r + 30 and g > b + 30:
            signal = "🟢 BUY"
        elif r > g + 30 and r > b + 30:
            signal = "🔴 SELL"
            
        if not signal:
            return None, None

        # 2. OCR for Price (Only run if we found a colored signal)
        text = pytesseract.image_to_string(image)
        # Regex to find prices like 124.50 or 1,200.00
        prices = re.findall(r'[\$]?([\d,]+\.\d{2})', text)
        
        price = "Unknown"
        if prices:
            # Clean up commas and floats
            clean_prices = []
            for p in prices:
                try:
                    clean_prices.append(float(p.replace(',', '')))
                except:
                    pass
            if clean_prices:
                price = max(clean_prices) # Usually the big number is the price

        return signal, price

    except Exception:
        return None, None

def main():
    print("👁️  OPERATION RETINA V2: REMOTE SIGNAL HUNTER")
    print("---------------------------------------------")
    
    if not os.path.exists(CHART_DIR):
        os.makedirs(CHART_DIR)

    conn = get_db_connection()
    cur = conn.cursor()

    # Get HTML content from Market Intelligence
    print("   Fetching email intelligence...")
    cur.execute("SELECT sent_at, subject, content FROM email_archive WHERE category = 'Market Intelligence' AND content ILIKE '%<img%' ORDER BY sent_at DESC LIMIT 300")
    
    rows = cur.fetchall()
    print(f"   -> Scanning {len(rows)} recent alerts for chart links...")
    
    signals_found = 0
    downloaded_urls = set()

    for row in rows:
        sent_at, subject, content = row
        date_str = sent_at.strftime('%Y-%m-%d')
        
        # Extract all image URLs
        urls = re.findall(r'src="([^"]+)"', content)
        
        for url in urls:
            # Filter: Skip logos, pixels, and known junk
            if "logo" in url or "pixel" in url or "facebook" in url or url in downloaded_urls:
                continue
            
            try:
                # Download the image
                r = requests.get(url, timeout=5)
                if r.status_code == 200:
                    downloaded_urls.add(url)
                    
                    # Analyze
                    signal, price = analyze_image(r.content, date_str)
                    
                    if signal:
                        print(f"   {date_str} | {signal} | Price: ${price} | Ref: {subject[:30]}...")
                        signals_found += 1
                        
                        # Save Evidence
                        fname = f"{date_str}_{signal.split()[1]}_{price}.png"
                        with open(os.path.join(CHART_DIR, fname), 'wb') as f_out:
                            f_out.write(r.content)
                        
                        # Stop after finding the main signal in an email (efficiency)
                        break 
            except Exception:
                pass

    print(f"\n✅ Scan Complete. Extracted {signals_found} verified signals.")
    conn.close()

if __name__ == "__main__":
    main()
