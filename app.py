import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client
from datetime import datetime
import time

# --- 1. SETUP & CONFIGURATION ---
st.set_page_config(
    page_title="Fortress Legal Command v2",
    page_icon="🛡️",
    layout="wide"
)

# Initialize Supabase Connection
# We use st.secrets so your keys stay safe in the cloud settings
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    
    # FIXED: Clean connection line (No proxy argument)
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error(f"❌ Database Connection Failed: {e}")
    st.stop()

# --- 2. HELPER FUNCTIONS ---
def get_system_health():
    """Fetch the latest heartbeat for all nodes."""
    try:
        # Get all records
        response = supabase.table("system_health").select("*").execute()
        df = pd.DataFrame(response.data)
        
        if not df.empty:
            # Convert timestamp to datetime
            df['last_updated'] = pd.to_datetime(df['last_updated'])
            # Sort by time, so we get the latest
            df = df.sort_values(by="last_updated", ascending=False)
            # Keep only the latest entry for each unique node_id
            latest_status = df.drop_duplicates(subset=["node_id"], keep="first")
            return latest_status
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error fetching telemetry: {e}")
        return pd.DataFrame()

# --- 3. MAIN DASHBOARD UI ---
st.title("🛡️ Fortress Legal: Enterprise Cluster")
st.markdown("---")

# Create Tabs
tab1, tab2 = st.tabs(["📊 Hardware Telemetry", "📝 Legal Analysis"])

# === TAB 1: HARDWARE MONITOR ===
with tab1:
    col1, col2 = st.columns([1, 4])
    
    with col1:
        if st.button("🔄 Refresh Telemetry"):
            st.rerun()

    # Fetch Data
    node_data = get_system_health()

    if node_data.empty:
        st.warning("⚠️ No signals detected. Are the Spark servers running?")
    else:
        # Display Metrics for each Node
        st.subheader("🟢 Live Cluster Status")
        
        # Create a grid for the nodes
        cols = st.columns(len(node_data))
        
        for index, (i, row) in enumerate(node_data.iterrows()):
            # Determine which column to use
            current_col = cols[index % len(cols)]
            
            with current_col:
                # Icon based on Node Name
                icon = "⚓" if "Captain" in row['node_id'] or "2" in row['node_id'] else "🔥"
                
                with st.expander(f"{icon} {row['node_id']}", expanded=True):
                    # Time calculation for display
                    st.write(f"**Last Heartbeat:** {row['last_updated'].strftime('%H:%M:%S')}")
                    
                    # GPU TEMPERATURE GAUGE
                    st.metric("GPU Temp", f"{row['gpu_temp']}°C", delta_color="inverse")
                    
                    # VRAM USAGE
                    st.metric("VRAM Used", f"{row['vram_used']} MB")
                    
                    # LOAD BARS
                    st.write("CPU Load")
                    st.progress(int(row['cpu_usage']))
                    
                    st.write("RAM Usage")
                    st.progress(int(row['ram_usage']))
                    
                    st.write("GPU Load")
                    st.progress(int(row['gpu_util']))

# === TAB 2: LEGAL ANALYSIS (AI) ===
with tab2:
    st.header("📝 Intelligent Document Analysis")
    st.info("The Hardware Bridge is Active. Document Ingestion Pipeline coming next.")
    
    query = st.text_input("Query Case Files", placeholder="e.g., What are the key risks in the NDA?")
    
    if st.button("Analyze"):
        st.warning("⚠️ No vector store found. We need to upload documents first.")
