import streamlit as st
import pandas as pd
import plotly.express as px
import psycopg2
import subprocess
import os
import time
import sys
from streamlit_option_menu import option_menu

_MINER_BOT_PASSWORD = os.getenv("MINER_BOT_DB_PASSWORD")
if not _MINER_BOT_PASSWORD:
    raise RuntimeError("MINER_BOT_DB_PASSWORD env var required")


# --- CONFIGURATION ---
st.set_page_config(page_title="FORTRESS PRIME", page_icon="🛡️", layout="wide")

# --- CSS STYLING ---
st.markdown("""
    <style>
    /* Dark Theme Base */
    .stApp {
        background: linear-gradient(135deg, #0a0e27 0%, #1a1a2e 50%, #16213e 100%);
    }
    
    /* Metric Cards */
    .metric-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border: 2px solid #00ff88;
        padding: 30px;
        border-radius: 15px;
        margin-bottom: 20px;
        box-shadow: 0 8px 32px rgba(0, 255, 136, 0.2);
        transition: all 0.3s ease;
    }
    
    .metric-card:hover {
        box-shadow: 0 12px 48px rgba(0, 255, 136, 0.4);
        transform: translateY(-2px);
    }
    
    /* Price Display */
    .price-display {
        font-size: 72px;
        font-weight: 900;
        color: #00ff88;
        text-shadow: 0 0 20px rgba(0, 255, 136, 0.8), 0 0 40px rgba(0, 255, 136, 0.4);
        font-family: 'Courier New', monospace;
        letter-spacing: 2px;
        margin: 20px 0;
        text-align: center;
    }
    
    .price-label {
        font-size: 18px;
        color: #88aaff;
        text-transform: uppercase;
        letter-spacing: 3px;
        margin-bottom: 10px;
        text-align: center;
    }
    
    .price-change {
        font-size: 16px;
        color: #88aaff;
        text-align: center;
        margin-top: 10px;
    }
    
    /* Status Log */
    .status-log {
        background: rgba(10, 14, 39, 0.8);
        border: 1px solid #00ff88;
        border-radius: 10px;
        padding: 20px;
        max-height: 500px;
        overflow-y: auto;
        font-family: 'Courier New', monospace;
        font-size: 12px;
    }
    
    .log-entry {
        color: #00ff88;
        padding: 8px;
        border-bottom: 1px solid rgba(0, 255, 136, 0.2);
        margin-bottom: 5px;
    }
    
    .log-timestamp {
        color: #88aaff;
        font-size: 10px;
    }
    
    /* Status Indicators */
    .status-online {color: #00ff88; font-weight: bold; text-shadow: 0 0 10px rgba(0, 255, 136, 0.8);}
    .status-offline {color: #ff4444; font-weight: bold; text-shadow: 0 0 10px rgba(255, 68, 68, 0.8);}
    .status-cloud {color: #ffaa00; font-weight: bold; text-shadow: 0 0 10px rgba(255, 170, 0, 0.8);}
    
    /* Captain Log */
    .captain-panel {
        background: rgba(10, 14, 39, 0.6);
        border-radius: 18px;
        padding: 22px;
        border: 2px solid rgba(255, 170, 0, 0.55);
        box-shadow: 0 10px 36px rgba(255, 170, 0, 0.18);
        margin-top: 18px;
    }
    .captain-title {
        font-size: 18px;
        color: #ffcc66;
        text-transform: uppercase;
        letter-spacing: 3px;
        margin-bottom: 14px;
        text-align: left;
        text-shadow: 0 0 12px rgba(255, 170, 0, 0.8);
        font-weight: 800;
    }
    .captain-log {
        background: rgba(10, 14, 39, 0.7);
        border: 1px solid rgba(255, 170, 0, 0.25);
        border-radius: 12px;
        padding: 12px;
        max-height: 320px;
        overflow-y: auto;
        font-family: 'Courier New', monospace;
        font-size: 11px;
        color: #ffcc66;
    }
    .captain-log-entry {
        padding: 6px 4px;
        border-bottom: 1px solid rgba(255, 170, 0, 0.12);
        line-height: 1.4;
    }
    .captain-log-entry:last-child { border-bottom: none; }
    .captain-log-entry.error { color: #ff6666; }
    .captain-log-entry.info { color: #ffcc66; }
    
    /* Refresh Button */
    .refresh-button {
        background: linear-gradient(135deg, #00ff88 0%, #00cc6a 100%);
        color: #0a0e27;
        border: none;
        padding: 12px 30px;
        border-radius: 8px;
        font-weight: bold;
        font-size: 16px;
        cursor: pointer;
        box-shadow: 0 4px 15px rgba(0, 255, 136, 0.4);
        transition: all 0.3s ease;
    }
    
    .refresh-button:hover {
        box-shadow: 0 6px 20px rgba(0, 255, 136, 0.6);
        transform: translateY(-2px);
    }
    
    /* Column Styling */
    .command-column {
        background: rgba(10, 14, 39, 0.5);
        border-radius: 15px;
        padding: 20px;
        border: 1px solid rgba(0, 255, 136, 0.3);
    }
    
    /* Enterprise Data Lake - Blue Glow */
    .lake-column {
        background: rgba(10, 14, 39, 0.5);
        border-radius: 15px;
        padding: 20px;
        border: 2px solid #4488ff;
        box-shadow: 0 8px 32px rgba(68, 136, 255, 0.3);
        transition: all 0.3s ease;
    }
    
    .lake-column:hover {
        box-shadow: 0 12px 48px rgba(68, 136, 255, 0.5);
        transform: translateY(-2px);
    }
    
    .lake-label {
        font-size: 18px;
        color: #88bbff;
        text-transform: uppercase;
        letter-spacing: 3px;
        margin-bottom: 15px;
        text-align: center;
        text-shadow: 0 0 10px rgba(68, 136, 255, 0.8);
    }
    
    .lake-zone {
        background: rgba(10, 14, 39, 0.7);
        border: 1px solid rgba(68, 136, 255, 0.4);
        border-radius: 10px;
        padding: 15px;
        margin-bottom: 15px;
    }
    
    .lake-zone-name {
        font-size: 14px;
        color: #88bbff;
        text-transform: uppercase;
        letter-spacing: 2px;
        margin-bottom: 8px;
    }
    
    .lake-count {
        font-size: 36px;
        font-weight: 900;
        color: #4488ff;
        text-shadow: 0 0 15px rgba(68, 136, 255, 0.8), 0 0 30px rgba(68, 136, 255, 0.4);
        font-family: 'Courier New', monospace;
        letter-spacing: 1px;
        text-align: center;
    }

    /* Vault Status - Cyan Glow */
    .vault-panel {
        background: rgba(10, 14, 39, 0.6);
        border-radius: 18px;
        padding: 22px;
        border: 2px solid rgba(0, 212, 255, 0.55);
        box-shadow: 0 10px 36px rgba(0, 212, 255, 0.18);
        margin-top: 18px;
    }
    .vault-title {
        font-size: 18px;
        color: #9be7ff;
        text-transform: uppercase;
        letter-spacing: 3px;
        margin-bottom: 14px;
        text-align: left;
        text-shadow: 0 0 12px rgba(0, 212, 255, 0.8);
        font-weight: 800;
    }
    .vault-metrics {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 12px;
        margin-bottom: 14px;
    }
    .vault-metric {
        background: rgba(10, 14, 39, 0.65);
        border: 1px solid rgba(0, 212, 255, 0.28);
        border-radius: 12px;
        padding: 12px;
    }
    .vault-metric-label {
        font-size: 11px;
        color: rgba(155, 231, 255, 0.9);
        letter-spacing: 2px;
        text-transform: uppercase;
        margin-bottom: 6px;
    }
    .vault-metric-value {
        font-size: 22px;
        color: #00d4ff;
        font-weight: 900;
        font-family: 'Courier New', monospace;
        text-shadow: 0 0 12px rgba(0, 212, 255, 0.65);
    }
    .vault-list {
        background: rgba(10, 14, 39, 0.7);
        border: 1px solid rgba(0, 212, 255, 0.25);
        border-radius: 12px;
        padding: 12px;
        max-height: 320px;
        overflow-y: auto;
        font-family: 'Courier New', monospace;
        font-size: 12px;
    }
    .vault-row {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        padding: 8px 6px;
        border-bottom: 1px solid rgba(0, 212, 255, 0.12);
        color: rgba(155, 231, 255, 0.95);
    }
    .vault-row:last-child { border-bottom: none; }
    .vault-folder { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 70%; }
    .vault-count { color: #00d4ff; font-weight: 900; text-shadow: 0 0 10px rgba(0, 212, 255, 0.55); }
    
    /* Progress Bar */
    .progress-container {
        margin-top: 14px;
        margin-bottom: 14px;
    }
    .progress-label {
        font-size: 11px;
        color: rgba(155, 231, 255, 0.9);
        letter-spacing: 2px;
        text-transform: uppercase;
        margin-bottom: 6px;
        display: flex;
        justify-content: space-between;
    }
    .progress-bar-bg {
        background: rgba(10, 14, 39, 0.8);
        border: 1px solid rgba(0, 212, 255, 0.3);
        border-radius: 8px;
        height: 24px;
        overflow: hidden;
        position: relative;
    }
    .progress-bar-fill {
        background: linear-gradient(90deg, #00d4ff 0%, #00a8cc 100%);
        height: 100%;
        transition: width 0.5s ease;
        box-shadow: 0 0 15px rgba(0, 212, 255, 0.6);
        display: flex;
        align-items: center;
        justify-content: center;
        color: #0a0e27;
        font-weight: 900;
        font-size: 11px;
        letter-spacing: 1px;
    }
    
    /* Scrollbar Styling */
    .status-log::-webkit-scrollbar {
        width: 8px;
    }
    
    .status-log::-webkit-scrollbar-track {
        background: rgba(10, 14, 39, 0.5);
        border-radius: 10px;
    }
    
    .status-log::-webkit-scrollbar-thumb {
        background: #00ff88;
        border-radius: 10px;
    }
    
    .status-log::-webkit-scrollbar-thumb:hover {
        background: #00cc6a;
    }
    
    /* Hide Streamlit default elements */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    </style>
    
    <script>
    // Matrix-style auto-scroll for log windows (Cinematic Fix)
    (function() {
        function autoScrollLogs() {
            // Scroll System Log to bottom (newest entries)
            const systemLog = document.querySelector('.status-log');
            if (systemLog) {
                systemLog.scrollTop = systemLog.scrollHeight;
            }
            
            // Scroll Captain Log to bottom (newest entries)
            const captainLog = document.querySelector('.captain-log');
            if (captainLog) {
                captainLog.scrollTop = captainLog.scrollHeight;
            }
        }
        
        // Run immediately
        autoScrollLogs();
        
        // Run after DOM is ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', autoScrollLogs);
        }
        
        // Run after delays to catch Streamlit's dynamic rendering
        setTimeout(autoScrollLogs, 100);
        setTimeout(autoScrollLogs, 300);
        setTimeout(autoScrollLogs, 600);
        
        // Watch for Streamlit reruns (when content changes)
        const observer = new MutationObserver(function(mutations) {
            let shouldScroll = false;
            mutations.forEach(function(mutation) {
                if (mutation.addedNodes.length > 0 || mutation.type === 'childList') {
                    shouldScroll = true;
                }
            });
            if (shouldScroll) {
                setTimeout(autoScrollLogs, 50);
            }
        });
        
        // Observe the main app container for changes
        const appContainer = document.querySelector('.stApp') || document.body;
        if (appContainer) {
            observer.observe(appContainer, {
                childList: true,
                subtree: true,
                attributes: false
            });
        }
        
        // Also listen for Streamlit's custom events if available
        window.addEventListener('load', autoScrollLogs);
    })();
    </script>
""", unsafe_allow_html=True)

# --- BACKEND FUNCTIONS ---
def get_db_conn():
    try:
        return psycopg2.connect(host="localhost", database="fortress_db", user="miner_bot", password=_MINER_BOT_PASSWORD)
    except:
        return None

def get_latest_price(symbol):
    """Get the latest price for a given symbol"""
    conn = get_db_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT price, timestamp 
                FROM market_signals 
                WHERE symbol = %s 
                ORDER BY timestamp DESC 
                LIMIT 1
            """, (symbol,))
            result = cur.fetchone()
            conn.close()
            if result:
                return {"price": float(result[0]), "timestamp": result[1]}
        except Exception as e:
            if conn:
                conn.close()
    return None

def get_price_history(symbol, limit=2):
    """Get recent price history for calculating change"""
    conn = get_db_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT price, timestamp 
                FROM market_signals 
                WHERE symbol = %s 
                ORDER BY timestamp DESC 
                LIMIT %s
            """, (symbol, limit))
            results = cur.fetchall()
            conn.close()
            return [{"price": float(r[0]), "timestamp": r[1]} for r in results]
        except Exception as e:
            if conn:
                conn.close()
    return []

def get_lake_status():
    """Get file counts for Landing Zone and Refined Zone from lake_status table"""
    import re
    conn = get_db_conn()
    if conn:
        try:
            cur = conn.cursor()
            # Check if table exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'lake_status'
                );
            """)
            table_exists = cur.fetchone()[0]
            
            if not table_exists:
                conn.close()
                return {"landing_zone": 0, "refined_zone": 0}
            
            # Get column names
            cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'lake_status'
                ORDER BY ordinal_position
            """)
            columns = [row[0] for row in cur.fetchall()]
            
            if not columns:
                conn.close()
                return {"landing_zone": 0, "refined_zone": 0}
            
            # Try to find zone and count columns
            zone_col = None
            count_col = None
            
            for col in columns:
                col_lower = col.lower()
                if 'zone' in col_lower or 'name' in col_lower:
                    zone_col = col
                if 'count' in col_lower or 'files' in col_lower or 'file_count' in col_lower or 'total' in col_lower:
                    count_col = col
            
            landing_count = 0
            refined_count = 0
            
            if zone_col and count_col:
                # Query with zone and count columns
                cur.execute(f"""
                    SELECT {zone_col}, {count_col}
                    FROM lake_status
                """)
                results = cur.fetchall()
                
                for row in results:
                    zone_name = str(row[0]).lower() if row[0] else ""
                    count = int(row[1]) if row[1] is not None else 0
                    if 'landing' in zone_name:
                        landing_count = count
                    elif 'refined' in zone_name:
                        refined_count = count
            else:
                # Fallback: get all data and try to parse
                cur.execute("SELECT * FROM lake_status")
                results = cur.fetchall()
                
                for row in results:
                    # Convert entire row to string and search
                    row_str = ' '.join([str(cell) if cell else '' for cell in row]).lower()
                    
                    # Extract numbers from row
                    numbers = re.findall(r'\d+', row_str)
                    
                    if 'landing' in row_str and numbers:
                        landing_count = max(landing_count, int(numbers[-1]))
                    if 'refined' in row_str and numbers:
                        refined_count = max(refined_count, int(numbers[-1]))
            
            conn.close()
            return {"landing_zone": landing_count, "refined_zone": refined_count}
                
        except Exception as e:
            if conn:
                conn.close()
            return {"landing_zone": 0, "refined_zone": 0}
    return {"landing_zone": 0, "refined_zone": 0}


def get_enterprise_lake_index():
    """Read folder file counts written by src/mailplus_sentinel.py."""
    conn = get_db_conn()
    if not conn:
        return pd.DataFrame(columns=["folder_name", "file_count", "scanned_at"])
    try:
        df = pd.read_sql(
            """
            SELECT folder_name, file_count, scanned_at
            FROM enterprise_lake_index
            ORDER BY file_count DESC, folder_name ASC
            """,
            conn,
        )
        return df
    except Exception:
        return pd.DataFrame(columns=["folder_name", "file_count", "scanned_at"])
    finally:
        try:
            conn.close()
        except Exception:
            pass

def get_processed_email_count():
    """Get count of processed emails from email_archive table."""
    conn = get_db_conn()
    if not conn:
        return 0
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM email_archive")
        count = cur.fetchone()[0]
        conn.close()
        return int(count) if count else 0
    except Exception:
        if conn:
            try:
                conn.close()
            except:
                pass
        return 0

def get_fleet_status():
    """Get Spark-1/Spark-2 status from node_telemetry table using last_seen column."""
    conn = get_db_conn()
    if not conn:
        return []
    try:
        df = pd.read_sql(
            """
            SELECT node_name, last_seen, gpu_temp, gpu_load, vram_usage
            FROM node_telemetry
            ORDER BY last_seen DESC
            LIMIT 10
            """,
            conn,
        )
        return df.to_dict('records')
    except Exception:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass

def read_captain_log(log_path="/home/admin/marketclub-ai/captain.log", lines=10):
    """Read last N lines from captain.log file."""
    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            all_lines = f.readlines()
            return all_lines[-lines:] if len(all_lines) > lines else all_lines
    except FileNotFoundError:
        return [f"⚠️ Log file not found: {log_path}\n"]
    except Exception as e:
        return [f"⚠️ Error reading log: {str(e)}\n"]

def get_node_status(node_type):
    stats = {"temp": 0, "load": 0, "status": "OFFLINE"}
    
    # SPARK-2 (Local)
    if node_type == "local":
        try:
            load = os.getloadavg()[0] * 10
            stats = {"temp": 45, "load": round(load, 1), "status": "ONLINE"}
        except: pass
            
    # SPARK-1 (SSH Remote)
    elif node_type == "remote":
        try:
            cmd = 'ssh -i ~/.ssh/id_fortress -o ConnectTimeout=1 -o StrictHostKeyChecking=no admin@192.168.0.104 "nvidia-smi --query-gpu=temperature.gpu,utilization.gpu --format=csv,noheader,nounits"'
            output = subprocess.check_output(cmd, shell=True).decode().strip()
            parts = output.split(',')
            if len(parts) >= 1:
                stats["temp"] = int(parts[0])
                stats["load"] = int(parts[1]) if len(parts) > 1 else 0
                stats["status"] = "ONLINE"
        except: pass
            
    return stats

# --- SIDEBAR ---
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/000000/fortress.png", width=50)
    st.title("FORTRESS PRIME")
    page = option_menu(
        menu_title=None,
        options=["Command Center", "Financial Intelligence", "War Room"],
        icons=["hdd-network", "graph-up-arrow", "layers"],
        default_index=0,
        styles={"nav-link-selected": {"background-color": "#00FF00", "color": "black"}}
    )
    st.markdown("---")
    st.caption("System Status: OPERATIONAL")

# --- PAGE 1: COMMAND CENTER ---
if page == "Command Center":
    # Initialize session state for status log
    if 'status_log' not in st.session_state:
        st.session_state.status_log = []
    
    # Header with Refresh Button
    header_col1, header_col2 = st.columns([3, 1])
    with header_col1:
        st.title("🛡️ COMMAND CENTER")
    with header_col2:
        if st.button("🔄 REFRESH", key="refresh_btn", use_container_width=True):
            st.session_state.status_log.append({
                "timestamp": time.strftime("%H:%M:%S"),
                "message": "Manual refresh initiated"
            })
            st.rerun()
    
    # 4-Column Layout
    col1, col2, col3, col4 = st.columns(4)
    
    # Column 1: Bitcoin Price
    with col1:
        st.markdown('<div class="command-column">', unsafe_allow_html=True)
        btc_data = get_latest_price("BTC-USD")
        btc_history = get_price_history("BTC-USD", 2)
        
        if btc_data:
            price = btc_data['price']
            change = ""
            if len(btc_history) >= 2:
                prev_price = btc_history[1]['price']
                diff = price - prev_price
                pct_change = (diff / prev_price) * 100
                change_symbol = "▲" if diff >= 0 else "▼"
                change_color = "#00ff88" if diff >= 0 else "#ff4444"
                change = f'<div class="price-change" style="color: {change_color};">{change_symbol} ${abs(diff):,.2f} ({abs(pct_change):.2f}%)</div>'
            
            st.markdown(f'''
                <div class="price-label">BITCOIN</div>
                <div class="price-display">${price:,.2f}</div>
                {change}
            ''', unsafe_allow_html=True)
            
            # Add to status log (only if price changed)
            last_btc_log = next((log for log in reversed(st.session_state.status_log) if log.get("message", "").startswith("BTC:")), None)
            if not last_btc_log or last_btc_log.get("message") != f"BTC: ${price:,.2f}":
                st.session_state.status_log.append({
                    "timestamp": time.strftime("%H:%M:%S"),
                    "message": f"BTC: ${price:,.2f}"
                })
        else:
            st.markdown('''
                <div class="price-label">BITCOIN</div>
                <div class="price-display" style="font-size: 24px; color: #ff4444;">NO DATA</div>
            ''', unsafe_allow_html=True)
            # Only log once if data unavailable
            last_btc_log = next((log for log in reversed(st.session_state.status_log) if "BTC" in log.get("message", "")), None)
            if not last_btc_log or "unavailable" not in last_btc_log.get("message", ""):
                st.session_state.status_log.append({
                    "timestamp": time.strftime("%H:%M:%S"),
                    "message": "⚠️ BTC data unavailable"
                })
        
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Column 2: Nvidia Price
    with col2:
        st.markdown('<div class="command-column">', unsafe_allow_html=True)
        nvda_data = get_latest_price("NVDA")
        nvda_history = get_price_history("NVDA", 2)
        
        if nvda_data:
            price = nvda_data['price']
            change = ""
            if len(nvda_history) >= 2:
                prev_price = nvda_history[1]['price']
                diff = price - prev_price
                pct_change = (diff / prev_price) * 100
                change_symbol = "▲" if diff >= 0 else "▼"
                change_color = "#00ff88" if diff >= 0 else "#ff4444"
                change = f'<div class="price-change" style="color: {change_color};">{change_symbol} ${abs(diff):,.2f} ({abs(pct_change):.2f}%)</div>'
            
            st.markdown(f'''
                <div class="price-label">NVIDIA</div>
                <div class="price-display">${price:,.2f}</div>
                {change}
            ''', unsafe_allow_html=True)
            
            # Add to status log (only if price changed)
            last_nvda_log = next((log for log in reversed(st.session_state.status_log) if log.get("message", "").startswith("NVDA:")), None)
            if not last_nvda_log or last_nvda_log.get("message") != f"NVDA: ${price:,.2f}":
                st.session_state.status_log.append({
                    "timestamp": time.strftime("%H:%M:%S"),
                    "message": f"NVDA: ${price:,.2f}"
                })
        else:
            st.markdown('''
                <div class="price-label">NVIDIA</div>
                <div class="price-display" style="font-size: 24px; color: #ff4444;">NO DATA</div>
            ''', unsafe_allow_html=True)
            # Only log once if data unavailable
            last_nvda_log = next((log for log in reversed(st.session_state.status_log) if "NVDA" in log.get("message", "")), None)
            if not last_nvda_log or "unavailable" not in last_nvda_log.get("message", ""):
                st.session_state.status_log.append({
                    "timestamp": time.strftime("%H:%M:%S"),
                    "message": "⚠️ NVDA data unavailable"
                })
        
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Column 3: Status Log
    with col3:
        st.markdown('<div class="command-column">', unsafe_allow_html=True)
        st.markdown('<div class="price-label">SYSTEM LOG</div>', unsafe_allow_html=True)
        
        # Keep only last 20 log entries
        if len(st.session_state.status_log) > 20:
            st.session_state.status_log = st.session_state.status_log[-20:]
        
        # Display log entries (newest first)
        log_html = '<div class="status-log">'
        for entry in reversed(st.session_state.status_log[-15:]):  # Show last 15 entries
            log_html += f'''
                <div class="log-entry">
                    <span class="log-timestamp">[{entry["timestamp"]}]</span> {entry["message"]}
                </div>
            '''
        log_html += '</div>'
        st.markdown(log_html, unsafe_allow_html=True)
        
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Column 4: Enterprise Data Lake
    with col4:
        st.markdown('<div class="lake-column">', unsafe_allow_html=True)
        lake_data = get_lake_status()
        
        st.markdown('<div class="lake-label">📦 ENTERPRISE DATA LAKE</div>', unsafe_allow_html=True)
        
        # Landing Zone
        st.markdown('''
            <div class="lake-zone">
                <div class="lake-zone-name">LANDING ZONE</div>
                <div class="lake-count">{:,}</div>
            </div>
        '''.format(lake_data["landing_zone"]), unsafe_allow_html=True)
        
        # Refined Zone
        st.markdown('''
            <div class="lake-zone">
                <div class="lake-zone-name">REFINED ZONE</div>
                <div class="lake-count">{:,}</div>
            </div>
        '''.format(lake_data["refined_zone"]), unsafe_allow_html=True)
        
        # Add to status log
        total_files = lake_data["landing_zone"] + lake_data["refined_zone"]
        last_lake_log = next((log for log in reversed(st.session_state.status_log) if "DATA LAKE" in log.get("message", "")), None)
        if not last_lake_log or f"LZ:{lake_data['landing_zone']}" not in last_lake_log.get("message", ""):
            st.session_state.status_log.append({
                "timestamp": time.strftime("%H:%M:%S"),
                "message": f"📦 DATA LAKE: LZ:{lake_data['landing_zone']:,} RZ:{lake_data['refined_zone']:,}"
            })
        
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Vault Status (enterprise_lake_index)
    vault_df = get_enterprise_lake_index()
    st.markdown(
        """
        <div class="vault-panel">
          <div class="vault-title">🧰 VAULT STATUS</div>
        """,
        unsafe_allow_html=True,
    )

    if vault_df.empty:
        st.markdown(
            """
            <div class="vault-list">
              <div class="vault-row">
                <div class="vault-folder">No enterprise lake index data yet.</div>
                <div class="vault-count">RUN SENTINEL</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        total_folders = int(vault_df["folder_name"].nunique())
        total_files = int(vault_df["file_count"].fillna(0).sum())
        last_scan = vault_df["scanned_at"].max()
        last_scan_str = str(last_scan) if pd.notna(last_scan) else "UNKNOWN"

        st.markdown(
            f"""
            <div class="vault-metrics">
              <div class="vault-metric">
                <div class="vault-metric-label">FOLDERS</div>
                <div class="vault-metric-value">{total_folders:,}</div>
              </div>
              <div class="vault-metric">
                <div class="vault-metric-label">TOTAL FILES</div>
                <div class="vault-metric-value">{total_files:,}</div>
              </div>
              <div class="vault-metric">
                <div class="vault-metric-label">LAST SCAN</div>
                <div class="vault-metric-value" style="font-size: 14px;">{last_scan_str}</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        
        # Progress Bar: Processed vs Total
        processed_count = get_processed_email_count()
        if total_files > 0:
            completion_pct = min(100.0, (processed_count / total_files) * 100)
            remaining = total_files - processed_count
            progress_html = f'''
            <div class="progress-container">
              <div class="progress-label">
                <span>PROCESSING STATUS</span>
                <span>{completion_pct:.1f}%</span>
              </div>
              <div class="progress-bar-bg">
                <div class="progress-bar-fill" style="width: {completion_pct}%;">
                  {completion_pct:.1f}%
                </div>
              </div>
              <div style="font-size: 10px; color: rgba(155, 231, 255, 0.7); margin-top: 4px; text-align: center;">
                {processed_count:,} / {total_files:,} processed • {remaining:,} remaining
              </div>
            </div>
            '''
            st.markdown(progress_html, unsafe_allow_html=True)

        # Render top folders by file_count
        top_n = 20
        rows_html = '<div class="vault-list">'
        for _, row in vault_df.head(top_n).iterrows():
            folder = str(row.get("folder_name", ""))
            count = int(row.get("file_count") or 0)
            rows_html += f'<div class="vault-row"><div class="vault-folder">{folder}</div><div class="vault-count">{count:,}</div></div>'
        rows_html += "</div>"
        st.markdown(rows_html, unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)

    # Captain Log Section
    captain_log_lines = read_captain_log("/home/admin/marketclub-ai/captain.log", 10)
    st.markdown(
        """
        <div class="captain-panel">
          <div class="captain-title">⚓ CAPTAIN LOG</div>
        """,
        unsafe_allow_html=True,
    )
    
    log_html = '<div class="captain-log" id="captain-log-container">'
    for line in captain_log_lines:
        line_clean = line.strip()
        if not line_clean:
            continue
        entry_class = "error" if "ERROR" in line_clean.upper() else "info"
        # Escape HTML and limit line length
        line_escaped = line_clean.replace('<', '&lt;').replace('>', '&gt;')[:200]
        log_html += f'<div class="captain-log-entry {entry_class}">{line_escaped}</div>'
    log_html += '</div>'
    st.markdown(log_html, unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    # System Status Footer - Fleet Status
    st.markdown("---")
    fleet_data = get_fleet_status()
    footer_col1, footer_col2, footer_col3, footer_col4 = st.columns(4)
    
    with footer_col1:
        s2 = get_node_status("local")
        st.markdown(f'''<div class="metric-card" style="padding: 15px;"><h4>⚓ Spark-2</h4><p>Status: <span class="status-online">ONLINE</span></p><p>CPU Load: {s2['load']}%</p></div>''', unsafe_allow_html=True)
    
    with footer_col2:
        # Use node_telemetry data for Spark-1 if available
        spark1_data = next((node for node in fleet_data if node.get('node_name', '').lower() == 'spark-1'), None)
        if spark1_data:
            last_seen = spark1_data.get('last_seen', '')
            gpu_temp = spark1_data.get('gpu_temp', 0)
            gpu_load = spark1_data.get('gpu_load', 0)
            # Check if last_seen is recent (within last 60 seconds)
            try:
                from datetime import datetime, timedelta
                if isinstance(last_seen, str):
                    last_seen_dt = datetime.fromisoformat(last_seen.replace('Z', '+00:00'))
                else:
                    last_seen_dt = last_seen
                if isinstance(last_seen_dt, datetime):
                    age = (datetime.now(last_seen_dt.tzinfo) - last_seen_dt).total_seconds() if last_seen_dt.tzinfo else (datetime.now() - last_seen_dt.replace(tzinfo=None)).total_seconds()
                    status = "ONLINE" if age < 60 else "STALE"
                    status_class = "status-online" if status == "ONLINE" else "status-offline"
                else:
                    status = "ONLINE"
                    status_class = "status-online"
            except:
                status = "ONLINE"
                status_class = "status-online"
            st.markdown(f'''<div class="metric-card" style="padding: 15px;"><h4>⚒️ Spark-1</h4><p>Status: <span class="{status_class}">{status}</span></p><p>GPU Temp: {gpu_temp:.0f}°C | Load: {gpu_load:.0f}%</p></div>''', unsafe_allow_html=True)
        else:
            # Fallback to SSH method
            s1 = get_node_status("remote")
            cls = "status-online" if s1['status'] == "ONLINE" else "status-offline"
            st.markdown(f'''<div class="metric-card" style="padding: 15px;"><h4>⚒️ Spark-1</h4><p>Status: <span class="{cls}">{s1['status']}</span></p><p>GPU Temp: {s1['temp']}°C</p></div>''', unsafe_allow_html=True)
    
    with footer_col3:
        conn_status = "ONLINE" if get_db_conn() else "OFFLINE"
        conn_class = "status-online" if conn_status == "ONLINE" else "status-offline"
        st.markdown(f'''<div class="metric-card" style="padding: 15px;"><h4>💾 Database</h4><p>Status: <span class="{conn_class}">{conn_status}</span></p></div>''', unsafe_allow_html=True)
    
    with footer_col4:
        # Supabase Connection Status (Yellow - Cloud)
        st.markdown(f'''<div class="metric-card" style="padding: 15px;"><h4>☁️ Supabase</h4><p>Status: <span class="status-cloud">CLOUD</span></p><p>Captain Active</p></div>''', unsafe_allow_html=True)

# --- PAGE 2: FINANCIAL INTELLIGENCE ---
elif page == "Financial Intelligence":
    st.title("📈 Market Analysis")
    conn = get_db_conn()
    if conn:
        try:
            df = pd.read_sql("SELECT symbol, price, timestamp FROM market_signals ORDER BY timestamp DESC LIMIT 50", conn)
            latest = df.iloc[0] if not df.empty else None
            m1, m2 = st.columns(2)
            if latest is not None:
                m1.metric("Latest Signal", latest['symbol'])
                m2.metric("Price", f"${latest['price']:,.2f}")
            st.subheader("Live Ticker Feed")
            st.dataframe(df)
        except Exception as e:
            st.warning("Waiting for data feed...")
    else:
        st.error("Database Disconnected")

# --- PAGE 3: WAR ROOM (UPDATED) ---
elif page == "War Room":
    st.title("🚀 War Room")
    conn = get_db_conn()
    if conn:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM images")
        img_count = cur.fetchone()[0]
        
        c1, c2 = st.columns(2)
        c1.metric("Database Status", "Connected", "Active")
        c2.metric("Total Asset Scans", img_count, "Images Processed")
        
        st.subheader("Latest Intelligence")
        df = pd.read_sql("SELECT id, filename, ai_description FROM images ORDER BY id DESC LIMIT 10", conn)
        st.dataframe(df, use_container_width=True)
    else:
        st.error("⚠️ Database Disconnected")

# Auto-refresh logic
time.sleep(3)
st.rerun()
