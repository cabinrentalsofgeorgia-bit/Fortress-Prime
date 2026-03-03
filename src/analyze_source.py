import json
import os
import collections

# --- CONFIG ---
REPORT_FILE = os.path.expanduser("~/Fortress-Prime/source_audit_report.json")

def analyze():
    print(f"📂 LOADING REPORT: {REPORT_FILE} (This may take a moment...)")
    if not os.path.exists(REPORT_FILE):
        print("❌ Report not found.")
        return

    with open(REPORT_FILE) as f:
        data = json.load(f)

    files = data.get("files", {})
    total_count = len(files)
    
    print(f"📊 ANALYZING {total_count:,} FILES...")

    # --- METRICS ---
    extensions = collections.defaultdict(int)
    folder_sizes = collections.defaultdict(int)
    hash_counts = collections.defaultdict(int)
    total_size = 0
    
    # Iterate and Crunch
    for path, meta in files.items():
        size = meta.get('size', 0)
        file_hash = meta.get('hash', 'unknown')
        
        # 1. Total Size
        total_size += size
        
        # 2. Extension Stats
        _, ext = os.path.splitext(path)
        ext = ext.lower()
        if ext == "": ext = "[no_extension]"
        extensions[ext] += 1
        
        # 3. Folder Size (Top Level)
        # Assumes structure /mnt/vol1_source/CATEGORY/SUB/...
        parts = path.split("/")
        if len(parts) > 4:
            # Group by /mnt/vol1_source/Category/ShareName
            top_folder = f"/{parts[3]}/{parts[4]}" 
        else:
            top_folder = "root"
        folder_sizes[top_folder] += size

        # 4. Duplicates
        if file_hash != "ERROR" and "SKIPPED" not in file_hash:
            hash_counts[file_hash] += 1

    # Calculate Duplicates
    dup_hashes = {k: v for k, v in hash_counts.items() if v > 1}
    dup_files_count = sum(v for v in dup_hashes.values())
    unique_hashes = len(hash_counts)
    
    # --- REPORTING ---
    print("\n" + "="*50)
    print(f"🏰 FORTRESS PRIME: SOURCE INTELLIGENCE REPORT")
    print("="*50)
    print(f"Total Files:       {total_count:,}")
    print(f"Total Data Volume: {total_size / (1024**3):.2f} GB")
    print(f"Duplicate Files:   {dup_files_count:,} (Copies of {len(dup_hashes):,} unique files)")
    print("-" * 50)
    
    print("\n📂 STORAGE BY TOP-LEVEL FOLDER (GB):")
    sorted_folders = sorted(folder_sizes.items(), key=lambda x: x[1], reverse=True)
    for folder, size in sorted_folders:
        gb = size / (1024**3)
        if gb > 0.1: # Show only significant folders
            print(f"   {folder:<40} : {gb:>8.2f} GB")

    print("\n📄 TOP 10 FILE TYPES (Count):")
    sorted_ext = sorted(extensions.items(), key=lambda x: x[1], reverse=True)[:10]
    for ext, count in sorted_ext:
        print(f"   {ext:<10} : {count:,}")

if __name__ == "__main__":
    analyze()
