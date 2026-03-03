import os
import requests
from fastapi import FastAPI, APIRouter, HTTPException
from pydantic import BaseModel

# --- CONFIGURATION ---
app = FastAPI(title="Fortress Sovereign Conglomerate")

# Router (exported for gateway mounting)
router = APIRouter()

# SOVEREIGN AI ENDPOINTS (Local Spark 2)
R1_URL = "http://localhost:11434/api/generate"
VISION_URL = "http://localhost:11434/api/generate" # Assumes Vision model is loaded here

# NAS DATA VAULTS (The Corporate Archives)
NAS_ROOT = "/mnt/fortress_nas/Enterprise_War_Room"
VAULTS = {
    "LEGAL":   os.path.join(NAS_ROOT, "Legal_Evidence"),
    "FINANCE": os.path.join(NAS_ROOT, "Financial_Records"),
    "TRADING": os.path.join(NAS_ROOT, "Fortress_Genisis"),
    "REAL_ESTATE": os.path.join(NAS_ROOT, "Property_Records"),
    "MEDIA":   os.path.join(NAS_ROOT, "Photos_Library"),
    "MARKETING": os.path.join(NAS_ROOT, "Web_Lab")
}

# --- EXECUTIVE PROTOCOL ---
class ExecutiveOrder(BaseModel):
    division: str
    task: str

def consult_r1(system_role, task, context=""):
    """Sends a strategic request to DeepSeek-R1"""
    prompt = f"""
    [SYSTEM] {system_role}
    [CONTEXT] {context}
    [TASK] {task}
    """
    payload = {"model": "deepseek-r1", "prompt": prompt, "stream": False}
    try:
        res = requests.post(R1_URL, json=payload, timeout=60)
        return res.json().get('response', "Agent Silent")
    except Exception as e:
        return f"Neural Link Severed: {e}"

# --- DIVISION ROUTER ---
@router.post("/execute")
def execute_order(order: ExecutiveOrder):
    div = order.division.upper()
    
    # DIVISION 1: LEGAL (Justicia)
    if div == "LEGAL":
        # TODO: Load ChromaDB Context here
        response = consult_r1("You are Justicia, the General Counsel.", order.task)
        return {"agent": "Justicia", "output": response}

    # DIVISION 2: FINANCE (Ledger)
    elif div == "FINANCE":
        # TODO: Load SQL/Tax Context here
        response = consult_r1("You are Ledger, the CFO.", order.task)
        return {"agent": "Ledger", "output": response}

    # DIVISION 3: TRADING (Titan)
    elif div == "TRADING":
        response = consult_r1("You are Titan, the Hedge Fund Manager.", order.task)
        return {"agent": "Titan", "output": response}
    
    # DIVISION 4: REAL ESTATE (Steward)
    elif div == "REAL_ESTATE":
        response = consult_r1("You are Steward, the Asset Manager.", order.task)
        return {"agent": "Steward", "output": response}

    # DIVISION 5: MEDIA (Maestro)
    elif div == "MEDIA":
        # Placeholder for Vision logic
        return {"agent": "Maestro", "status": "Vision Grid Online. Ready for photo stream."}

    # DIVISION 6: MARKETING (Herald)
    elif div == "MARKETING":
        response = consult_r1("You are Herald, the CMO.", order.task)
        return {"agent": "Herald", "output": response}

    else:
        raise HTTPException(404, detail="Division Does Not Exist")

@router.get("/status")
def system_status():
    return {"status": "OPERATIONAL", "vaults_connected": list(VAULTS.keys())}

# Standalone mode: include router on local app
app.include_router(router, prefix="/boardroom")

if __name__ == "__main__":
    import uvicorn
    # Host 0.0.0.0 exposes it to the Cloudflare Tunnel
    uvicorn.run(app, host="0.0.0.0", port=8000)
