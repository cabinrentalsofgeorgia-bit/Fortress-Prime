import time
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

# Load credentials
load_dotenv()

LOG_FILE = "/mnt/fortress_nas/fortress_data/ai_brain/logs/ocr_batch/gpu_marathon.log"
TARGET_STRING = "912/912"  # The "Mission Complete" signal

def send_alert():
    sender = os.getenv("GMAIL_ADDRESS")
    password = os.getenv("GMAIL_APP_PASSWORD")

    if not sender or not password:
        print("❌ Credentials missing in .env")
        return

    msg = MIMEMultipart()
    msg['From'] = f"Fortress Watch Tower <{sender}>"
    msg['To'] = sender
    msg['Subject'] = "🚀 SLINGSHOT ENGAGED: OCR Batch Complete"

    body = "The GPU Marathon is finished. File 912/912 processed.\n\nThe CFO Agent (Financials) will now accelerate.\n\nSystem is ready for Phase 5."
    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)
        server.quit()
        print("✅ Alert sent!")
    except Exception as e:
        print(f"❌ Email failed: {e}")

def main():
    print(f"🏰 Watch Tower active. Scanning {LOG_FILE} for '{TARGET_STRING}'...")
    while True:
        try:
            with open(LOG_FILE, "r") as f:
                # Read the last few lines to save I/O
                lines = f.readlines()[-20:]
                content = "".join(lines)

            if TARGET_STRING in content:
                print("\n🚀 TARGET ACQUIRED. Sending alert...")
                send_alert()
                break  # Mission done, exit script

            # Pulse check every 30 minutes
            time.sleep(1800)
        except FileNotFoundError:
            print("⏳ Log file not found yet. Waiting...")
            time.sleep(60)

if __name__ == "__main__":
    main()
