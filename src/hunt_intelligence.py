import sqlite3
import os

# --- CONFIG ---
DB_FILE = os.path.expanduser("~/Fortress-Prime/nas_master_index.db")

def hunt():
    print(f"🕵️  HUNTING FOR INTELLIGENCE ARTIFACTS (Index: 5.0M Files)")
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # 1. THE AI PROJECTS (Source Code)
    print("\n🧠 SECTION 1: AI PROJECTS (Source Code)")
    # We look for Jupyter Notebooks - the surest sign of "AI I Built"
    c.execute("SELECT path FROM files WHERE extension = '.ipynb' OR extension = '.py'")
    projects = {}
    for row in c.fetchall():
        path = row[0]
        folder = os.path.dirname(path)
        # Group by project folder
        if folder not in projects: projects[folder] = []
        projects[folder].append(os.path.basename(path))

    # Filter for interesting ones (ignore system python libs)
    found_projects = 0
    for folder, files in projects.items():
        if "site-packages" in folder or "/lib/" in folder: continue
        # If a folder has notebooks, it's a high-value target
        if any(f.endswith('.ipynb') for f in files):
            print(f"   📂 PROJECT FOUND: {folder}")
            for f in files[:3]: print(f"      - {f}")
            if len(files) > 3: print(f"      - ...and {len(files)-3} more scripts")
            found_projects += 1
            
    if found_projects == 0: print("   (No user-created AI notebooks found)")

    # 2. THE AI BRAINS (Models)
    print("\n🤖 SECTION 2: AI MODELS (Weights & Checkpoints)")
    c.execute("SELECT path, size FROM files WHERE extension IN ('.pt', '.pth', '.onnx', '.safetensors', '.h5', '.ckpt')")
    models = c.fetchall()
    
    # Sort by size (Big models are interesting)
    models.sort(key=lambda x: x[1], reverse=True)
    
    for path, size in models[:10]: # Top 10 biggest models
        mb = size / (1024*1024)
        print(f"   ⚖️  {mb:.1f} MB | {os.path.basename(path)}")
        print(f"       📍 {os.path.dirname(path)}")

    # 3. THE "CRUNCHED" DATA (The Hunt for GA Code)
    print("\n🏛️  SECTION 3: LARGE DATASETS (Potential 'Crunched' Code)")
    # If the GA Code was processed, it might be a CSV, JSON, or PICKLE file > 50MB
    c.execute("SELECT path, size FROM files WHERE size > 50000000 AND extension IN ('.csv', '.json', '.pkl', '.pickle', '.parquet', '.npy')")
    datasets = c.fetchall()
    
    found_ga = False
    for path, size in datasets:
        name = os.path.basename(path).lower()
        # Look for clues in the name
        if any(x in name for x in ['code', 'law', 'ga', 'state', 'ocga', 'data', 'dump', 'clean']):
            mb = size / (1024*1024)
            print(f"   📦 POTENTIAL MATCH: {mb:.1f} MB | {name}")
            print(f"       📍 {path}")
            found_ga = True
            
    if not found_ga:
        print("   (No obvious 'GA Code' datasets found in top-level files. Check inside SQL dumps?)")

    conn.close()

if __name__ == "__main__":
    hunt()
