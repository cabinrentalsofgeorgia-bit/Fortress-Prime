import sqlite3
import os

# --- CONFIG ---
DB_FILE = os.path.expanduser("~/Fortress-Prime/nas_master_index.db")
OUTPUT_FILE = os.path.expanduser("~/Fortress-Prime/full_folder_manifest.txt")

def generate_report():
    print(f"GENERATING FORENSIC FOLDER MAP")
    print(f"    Source: {DB_FILE}")
    
    if not os.path.exists(DB_FILE):
        print("Index missing. Run build_master_index.py first.")
        return

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # 1. Extract every unique folder path from the 719,000 files
    print("    ...Extracting folder paths (this takes ~10s)...")
    c.execute("SELECT DISTINCT path FROM files")
    
    unique_folders = set()
    for row in c.fetchall():
        # Strip the filename to get the folder
        folder_path = os.path.dirname(row[0])
        unique_folders.add(folder_path)
    
    # 2. Sort alphabetically so you can see the depth (A -> A/B -> A/B/C)
    sorted_folders = sorted(list(unique_folders))
    
    with open(OUTPUT_FILE, 'w') as f:
        f.write(f"FORTRESS PRIME - VERIFIED SCAN MANIFEST\n")
        f.write(f"Total Unique Folders Scanned: {len(sorted_folders):,}\n")
        f.write("="*60 + "\n")
        for folder in sorted_folders:
            f.write(f"{folder}\n")
            
    print("-" * 50)
    print(f"MANIFEST GENERATED: {OUTPUT_FILE}")
    print(f"    Unique Folders Visited: {len(sorted_folders):,}")
    print("-" * 50)
    print("PREVIEW (Top 10 Deepest Paths):")
    for folder in sorted_folders[:10]:
        print(f"   {folder}")

if __name__ == "__main__":
    generate_report()
