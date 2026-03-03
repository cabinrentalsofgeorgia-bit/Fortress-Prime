import json
import os

# --- CONFIG ---
INPUT_REPORT = os.path.expanduser("~/Fortress-Prime/nas_audit_report.json")
OUTPUT_MAP = os.path.expanduser("~/Fortress-Prime/nas_file_structure.txt")

def generate_tree():
    print(f"📂 READING AUDIT REPORT: {INPUT_REPORT}")
    if not os.path.exists(INPUT_REPORT):
        print("❌ Report not found.")
        return

    with open(INPUT_REPORT, 'r') as f:
        data = json.load(f)
    
    files = data.get("files", {})
    # Sort files by directory path so they group together
    paths = sorted([meta['path'] for meta in files.values()])

    print(f"🌳 GENERATING TREE MAP FOR {len(paths)} FILES...")
    
    with open(OUTPUT_MAP, 'w') as f:
        f.write("FORTRESS NAS - FULL FILE STRUCTURE\n")
        f.write("==================================\n")
        
        last_dir = ""
        for path in paths:
            directory, filename = os.path.split(path)
            
            # If the directory changes, print a new header
            if directory != last_dir:
                f.write(f"\n📁 {directory}\n")
                last_dir = directory
            
            # Print the file
            f.write(f"    📄 {filename}\n")

    print(f"✅ MAP GENERATED: {OUTPUT_MAP}")
    print("   Run this to view it: less ~/Fortress-Prime/nas_file_structure.txt")

if __name__ == "__main__":
    generate_tree()
