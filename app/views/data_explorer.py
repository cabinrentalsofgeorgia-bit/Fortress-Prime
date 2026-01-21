import streamlit as st
from app.modules.database import run_query

def render():
    st.header("💴 Data Vault")
    search = st.text_input("Search:", placeholder="Subject or Content")
    if search:
        q = "SELECT sent_at, sender, subject, content FROM email_archive WHERE content ILIKE %s LIMIT 50"
        df = run_query(q, (f"%{search}%",))
        st.dataframe(df)
    else:
        st.dataframe(run_query("SELECT sent_at, sender, subject FROM email_archive ORDER BY sent_at DESC LIMIT 50"))