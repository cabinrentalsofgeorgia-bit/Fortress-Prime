import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import SPARK_02_IP

# --- THE TWIN ENGINES (Ollama native on ARM64) ---
# Spark 2: Planner (DeepSeek R1 8B — swap to deepseek-r1:70b once downloaded)
PLANNER_URL = "http://localhost:11434/api/chat"
PLANNER_MODEL = "deepseek-r1:8b"

# Spark 1: Worker/Vision (Llama 3.2 Vision 90B via Ollama)
WORKER_URL = f"http://{SPARK_02_IP}:11434/api/chat"
WORKER_MODEL = "llama3.2-vision:90b"

def query_brain(url, model_name, prompt, system_role="You are a helpful assistant."):
    """Query an Ollama instance using /api/chat."""
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_role},
            {"role": "user", "content": prompt}
        ],
        "stream": False,
        "options": {
            "temperature": 0.6,
            "num_predict": 2048
        }
    }
    try:
        response = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=600)
        return response.json()['message']['content']
    except Exception as e:
        return f"Error contacting {model_name}: {e}"

def autonomous_agent(user_query):
    print(f"User: {user_query}")
    print("-" * 40)

    # PHASE 1: PLANNING (DeepSeek on Spark 2)
    print(f"🧠 PLANNER ({PLANNER_MODEL}) is thinking...")
    plan_prompt = f"""
    You are the CEO of an autonomous system.
    Analyze this request: '{user_query}'
    Break it down into a step-by-step plan for your worker.
    Return ONLY the numbered plan.
    """
    plan = query_brain(PLANNER_URL, PLANNER_MODEL, plan_prompt)
    print(f"📋 PLAN:\n{plan}\n")

    # PHASE 2: EXECUTION (Llama Vision on Spark 1)
    print(f"🔨 WORKER ({WORKER_MODEL}) is executing...")
    work_prompt = f"""
    You are the Worker. Follow this plan exactly:
    {plan}

    Provide the final answer to the user based on this plan.
    """
    result = query_brain(WORKER_URL, WORKER_MODEL, work_prompt)
    print(f"✅ RESULT:\n{result}")

if __name__ == "__main__":
    # Test the loop
    autonomous_agent("Analyze the risk of Bitcoin dropping below 50k and draft a short email to my partner about it.")
