import os

# Scan the entire Fortress Data mount
ROOT_DIR = "/mnt/fortress_data"

print(f"📡  Deep Scanning {ROOT_DIR} for Intelligence Assets...")
print("    (Looking for .mbox, .pst, .zip, and PDF clusters)")
print("-" * 60)

found_any = False

for dirpath, dirnames, filenames in os.walk(ROOT_DIR):
    
    # 1. Look for ARCHIVES (The Backups)
    archives = [f for f in filenames if f.lower().endswith(('.mbox', '.pst', '.zip', '.tar.gz'))]
    
    # 2. Look for PDF CLUSTERS (Market Reports)
    pdfs = [f for f in filenames if f.lower().endswith('.pdf')]
    
    # Report if we find anything significant
    if len(archives) > 0:
        found_any = True
        print(f"📦 ARCHIVE FOUND: {dirpath}")
        for arc in archives:
            size_mb = os.path.getsize(os.path.join(dirpath, arc)) / (1024*1024)
            print(f"   ├── 🗄️  {arc} ({size_mb:.1f} MB)")
            
    if len(pdfs) > 10:  # Only report if there are more than 10 PDFs
        found_any = True
        print(f"📄 DOCUMENT CLUSTER: {dirpath}")
        print(f"   └── Found {len(pdfs)} PDFs")

    if found_any:
        # Add a tiny separator if we found something in this folder
        print("-" * 60)
        found_any = False # Reset for next folder loop to avoid spamming logic

print("✅ Scan Complete.")
