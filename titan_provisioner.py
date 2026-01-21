import requests
import json
import sys
import time

# --- INFRASTRUCTURE CONFIGURATION ---
WORKER_IP = "192.168.0.104"
BASE_URL = f"http://{WORKER_IP}:11434/api"

# The "Desired State" - What MUST exist on the server
REQUIRED_MODELS = [
    "nomic-embed-text",  # The Librarian (Vector Embeddings)
    "mistral"            # The Writer (Chat / Text Generation)
]

def get_installed_models():
    """Queries the worker to see what is currently installed."""
    try:
        response = requests.get(f"{BASE_URL}/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            # Extract just the model names (e.g., 'mistral:latest')
            return [m['name'].split(':')[0] for m in data.get('models', [])]
        else:
            print(f"[!] API Error: {response.status_code}")
            return []
    except requests.exceptions.ConnectionError:
        print(f"[!] CRITICAL: Cannot connect to AI Worker at {WORKER_IP}")
        print("    Is the Ollama service running?")
        sys.exit(1)

def pull_model(model_name):
    """
    Enterprise Loader: Pulls the model with streaming progress updates.
    This prevents timeouts on large downloads.
    """
    print(f"[*] INITIATING DOWNLOAD: {model_name}...")
    url = f"{BASE_URL}/pull"
    payload = {"name": model_name}
    
    try:
        # Stream=True is critical for large files (4GB+)
        with requests.post(url, json=payload, stream=True) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line:
                    decoded = json.loads(line.decode('utf-8'))
                    status = decoded.get('status', '')
                    
                    # Enterprise Logging: Only show completion or major steps
                    if 'completed' in decoded and 'total' in decoded:
                        # Calculate percentage if total size is known
                        completed = decoded['completed']
                        total = decoded['total']
                        percent = int((completed / total) * 100)
                        sys.stdout.write(f"\r    -> Downloading {model_name}: {percent}% ({status})")
                        sys.stdout.flush()
                    elif status == "success":
                        print(f"\n[+] INSTALLED: {model_name} successfully provisioned.")
                    
    except Exception as e:
        print(f"\n[!] PROVISIONING FAILED for {model_name}: {e}")

def enforce_state():
    print(f"[*] TITAN PROVISIONER: Auditing AI Worker ({WORKER_IP})...")
    
    # 1. Audit Current State
    current_models = get_installed_models()
    print(f"    -> Detected Inventory: {current_models}")
    
    # 2. Compare against Desired State
    missing_models = [m for m in REQUIRED_MODELS if m not in current_models]
    
    if not missing_models:
        print("[+] SYSTEM COMPLIANT. All required models are active.")
        return

    # 3. Remediation (Fix the gaps)
    print(f"[!] COMPLIANCE GAP DETECTED. Missing: {missing_models}")
    for model in missing_models:
        pull_model(model)
        
    print("[*] Re-Auditing...")
    final_check = get_installed_models()
    if all(m in final_check for m in REQUIRED_MODELS):
        print("[+] PROVISIONING COMPLETE. System is ready.")
    else:
        print("[!] WARNING: Some models failed to install.")

if __name__ == "__main__":
    enforce_state()


