import time
import psycopg2
import subprocess
import os

# --- CONFIG ---
# Use environment variables when running in Docker, fallback to defaults
NODE_NAME = os.getenv("NODE_NAME", "spark-1")
DB_HOST = os.getenv("DB_HOST", "192.168.0.100")  # Address of Spark-2 or postgres container
DB_NAME = os.getenv("DB_NAME", "fortress_db")
DB_USER = os.getenv("DB_USER", "miner_bot")
DB_PASS = os.getenv("DB_PASS", "190AntiochCemeteryRD!!!")
INTERVAL = int(os.getenv("INTERVAL", "5"))  # Update every 5 seconds (Turbo Mode)

def get_hw_stats():
    # 1. Try NVIDIA GPU
    try:
        cmd = "nvidia-smi --query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits"
        out = subprocess.check_output(cmd, shell=True).decode().strip().split(',')
        return float(out[0]), float(out[1]), f"{out[2]}/{out[3]} MB"
    except:
        # 2. Fallback to CPU (If no GPU found)
        # Load: Average over last 1 min
        cpu_load = os.getloadavg()[0] * 10 
        
        # Temp: Try standard Linux thermal zone
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                cpu_temp = float(f.read()) / 1000.0
        except:
            cpu_temp = 0.0
            
        return cpu_temp, cpu_load, "CPU ONLY"

def send_pulse():
    temp, load, vram = get_hw_stats()
    try:
        conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
        cur = conn.cursor()
        
        # Upsert Data
        sql = """
            INSERT INTO node_telemetry (node_name, last_seen, gpu_temp, gpu_load, vram_usage)
            VALUES (%s, NOW(), %s, %s, %s)
            ON CONFLICT (node_name) 
            DO UPDATE SET last_seen=NOW(), gpu_temp=EXCLUDED.gpu_temp, gpu_load=EXCLUDED.gpu_load, vram_usage=EXCLUDED.vram_usage;
        """
        cur.execute(sql, (NODE_NAME, temp, load, vram))
        conn.commit()
        conn.close()
        print(f"🚀 Turbo Pulse: {temp}°C | Load: {load}% | {vram}")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    print(f"⚡ Starting Turbo Agent on {NODE_NAME}...")
    while True:
        send_pulse()
        time.sleep(INTERVAL)