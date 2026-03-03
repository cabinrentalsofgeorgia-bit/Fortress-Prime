import os
import psycopg2
import requests
import sys

# --- CONFIGURATION ---
DB_PASS = os.getenv("DB_PASS", os.getenv("ADMIN_DB_PASS", ""))
WORKER_IP = "192.168.0.104"
OLLAMA_API = f"http://{WORKER_IP}:11434/api/generate"
OLLAMA_EMBED = f"http://{WORKER_IP}:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text"
CHAT_MODEL = "mistral" # or 'llama3', whatever you have installed on the worker

def get_embedding(text):
    try:
        response = requests.post(OLLAMA_EMBED, json={"model": EMBED_MODEL, "prompt": text}, timeout=5)
        return response.json().get("embedding")
    except: return None

def ask_titan(question):
    print(f"\n[*] Analysing Neural Memory for: '{question}'...")
    
    # 1. Vectorize the Question
    vector = get_embedding(question)
    if not vector:
        print("[!] Error: Could not vectorize question.")
        return

    # 2. Search the Fortress Database
    try:
        conn = psycopg2.connect(host="localhost", database="fortress_db", user="miner_bot", password=DB_PASS)
        cur = conn.cursor()
        
        # Semantic Search Query
        cur.execute("""
            SELECT content, 1 - (embedding <=> %s::vector) as similarity
            FROM market_intel
            WHERE 1 - (embedding <=> %s::vector) > 0.4
            ORDER BY similarity DESC
            LIMIT 3
        """, (vector, vector))
        
        results = cur.fetchall()
        conn.close()
        
        if not results:
            print("[!] No relevant memories found in the database.")
            return

        # 3. Construct the Prompt for the AI
        context_block = ""
        print(f"[*] Found {len(results)} relevant data points.")
        for i, (content, score) in enumerate(results):
            print(f"    -> Source {i+1} Confidence: {round(score*100, 1)}%")
            context_block += f"-- SOURCE {i+1} --\n{content[:2000]}\n\n"

        prompt = f"""
        You are an AI assistant for 'Cabin Rentals of Georgia'. 
        Use the following retrieved context from our business archives to answer the user's question.
        If the answer is not in the context, say you don't know.

        CONTEXT FROM DATABASE:
        {context_block}

        USER QUESTION: 
        {question}
        """

        # 4. Generate Answer
        print("[*] Generating Response...")
        response = requests.post(OLLAMA_API, json={
            "model": CHAT_MODEL, 
            "prompt": prompt, 
            "stream": False
        }, timeout=300)
        
        if response.status_code == 200:
            answer = response.json()["response"]
            print("\n" + "="*60)
            print("TITAN SAYS:")
            print("="*60)
            print(answer)
            print("="*60 + "\n")
        else:
            print(f"[!] AI Generation Failed: {response.text}")

    except Exception as e:
        print(f"[!] System Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        ask_titan(" ".join(sys.argv[1:]))
    else:
        print("Usage: python3 titan_brain.py \"Your question here\"")
