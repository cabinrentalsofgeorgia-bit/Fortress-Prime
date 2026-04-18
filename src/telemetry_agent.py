import psutil
import psycopg2
import time
import socket
import os

_MINER_BOT_PASSWORD = os.getenv("MINER_BOT_DB_PASSWORD")
if not _MINER_BOT_PASSWORD:
    raise RuntimeError("MINER_BOT_DB_PASSWORD env var required")


# --- CONFIGURATION ---
DB_HOST = "127.0.0.1" 
DB_PASS = _MINER_BOT_PASSWORD
HOSTNAME = socket.gethostname()

def run_agent():
    print(f"🚀 HIGH-FREQUENCY AGENT STARTING on {HOSTNAME}")
    
    # 1. Connect ONCE
    try:
        conn = psycopg2.connect(host=DB_HOST, database="fortress_db", user="miner_bot", password=DB_PASS)
        cur = conn.cursor()
        print("✅ Database Connection Established (Persistent mode)")
    except Exception as e:
        print(f"❌ Initial Connection Failed: {e}")
        return

    # 2. Loop Forever using the SAME connection
    while True:
        try:
            cpu = psutil.cpu_percent(interval=1) # 1 second is the sweet spot
            ram = psutil.virtual_memory().percent
            try:
                disk = psutil.disk_usage('/').percent
            except:
                disk = 0

            cur.execute("INSERT INTO system_telemetry (hostname, cpu_usage, ram_usage, disk_usage, recorded_at) VALUES (%s, %s, %s, %s, NOW())", (HOSTNAME, cpu, ram, disk))
            conn.commit()
            
        except Exception as e:
            print(f"⚠️ Lost Connection: {e}")
            # If we lose connection, break the loop so the service restarts (or we logic a reconnect)
            break
            
    conn.close()

if __name__ == "__main__":
    while True:
        run_agent()
        time.sleep(5) # Wait before trying to reconnect if it crashed
