import os
import requests
import json

# CONFIG
R1_ENDPOINT = "http://localhost:11434/api/generate"
PROJECT_ROOT = "/home/admin/Fortress-Prime"

def consult_architect(goal, filename):
    print(f"🏗️  ARCHITECT: Drafting code for {filename}...")
    
    # Read existing code if it exists
    current_code = ""
    if os.path.exists(filename):
        with open(filename, 'r') as f: current_code = f.read()

    prompt = f"""
    [ROLE]
    You are the Chief Software Architect.
    
    [GOAL]
    {goal}
    
    [EXISTING CODE]
    {current_code}
    
    [INSTRUCTION]
    Write the complete, executable Python code to achieve the goal. 
    Include imports. Return ONLY the code inside python markdown blocks.
    """
    
    payload = {"model": "deepseek-r1", "prompt": prompt, "stream": False}
    
    try:
        res = requests.post(R1_ENDPOINT, json=payload, timeout=300)
        raw_output = res.json().get('response', '')
        
        # Extract Code
        if "```python" in raw_output:
            code = raw_output.split("```python")[1].split("```")[0]
            
            # Save Draft
            with open(filename, 'w') as f: f.write(code)
            print(f"✅ SUCCESS: Wrote updated code to {filename}")
        else:
            print("❌ ERROR: Architect did not return valid code.")
            
    except Exception as e:
        print(f"❌ CONNECTION ERROR: {e}")

if __name__ == "__main__":
    # Test Run
    print("Architect Online. Import this module to build.")
