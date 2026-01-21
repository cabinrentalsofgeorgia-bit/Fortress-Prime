import os
import re
import psycopg2
from pypdf import PdfReader
from collections import defaultdict

INVOICE_DIR = "/mnt/fortress_data/invoices"

def extract_amount(text):
    # Regex to find currency amounts
    patterns = [
        r"Total\s*:?\s*\$?\s*([\d,]+\.\d{2})",
        r"Amount Due\s*:?\s*\$?\s*([\d,]+\.\d{2})",
        r"\$([\d,]+\.\d{2})"
    ]
    amounts = []
    for p in patterns:
        matches = re.findall(p, text, re.IGNORECASE)
        for m in matches:
            try:
                amounts.append(float(m.replace(',', '')))
            except:
                pass
    return max(amounts) if amounts else 0.0

def main():
    print(f"💰 FORTRESS FINANCIAL INTELLIGENCE")
    print("-----------------------------------")
    vendor_spend = defaultdict(float)
    files = [f for f in os.listdir(INVOICE_DIR) if f.endswith('.pdf')]
    
    total_val = 0.0
    
    for filename in files:
        try:
            reader = PdfReader(os.path.join(INVOICE_DIR, filename))
            text = "".join([p.extract_text() for p in reader.pages])
            amount = extract_amount(text)
            
            # FIX: Handle double underscores and empty parts
            parts = [p for p in filename.split('_') if p.strip()]
            # parts[0] is Date, parts[1] is usually Vendor
            vendor = parts[1] if len(parts) > 1 else "Unknown"
            
            # Clean up vendor name
            vendor = vendor.replace('Inc', '').replace('LLC', '').strip()

            if amount > 0:
                vendor_spend[vendor] += amount
                total_val += amount
        except:
            pass

    print(f"📊 TOTAL AUDITED SPEND: ${total_val:,.2f}")
    print("\n🏆 VENDOR LEADERBOARD:")
    for v, s in sorted(vendor_spend.items(), key=lambda x: x[1], reverse=True):
        print(f"   🏢 {v.ljust(20)} : ${s:,.2f}")

if __name__ == "__main__":
    main()
