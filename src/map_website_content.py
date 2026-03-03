import os
import re
import csv

# --- CONFIG ---
LAB_ROOT = "/mnt/fortress_nas/Enterprise_War_Room/Web_Lab/Exploded"
OUTPUT_CSV = "/mnt/fortress_nas/Enterprise_War_Room/Web_Lab/site_content_map.csv"


def find_sql_dump():
    print(f"SEARCHING FOR DATABASE DUMPS...")
    dumps = []
    for root, dirs, files in os.walk(LAB_ROOT):
        for f in files:
            if f.endswith(".sql"):
                dumps.append(os.path.join(root, f))
    return dumps


def parse_content_from_sql(sql_file):
    print(f"FORENSIC READ OF DB: {os.path.basename(sql_file)}")
    content_map = []

    # Heuristic parsing to avoid needing a running MySQL server
    try:
        with open(sql_file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                # 1. Find Page Titles (Drupal 'node' / WP 'posts')
                if "INSERT INTO" in line and ("node" in line or "posts" in line):
                    # Look for text between quotes that looks like a title
                    titles = re.findall(r",'([^']{5,100})',", line)
                    for t in titles:
                        if " " in t:  # Filter out machine keys
                            content_map.append({"type": "Page Title", "value": t, "source": "DB"})

                # 2. Find URL Aliases (CRITICAL FOR SEO)
                if "url_alias" in line:
                    # Drupal format: (pid,'source','alias','language')
                    # Extract alias paths (no leading slash in Drupal)
                    aliases = re.findall(r",'([a-zA-Z0-9\-\_/][a-zA-Z0-9\-\_/ ]+)','(?:und|en)'", line)
                    for a in aliases:
                        # Skip internal Drupal paths like taxonomy/term/5, node/123
                        if a.startswith(('taxonomy/', 'node/', 'user/')):
                            continue
                        content_map.append({"type": "URL Alias", "value": "/" + a, "source": "DB"})
                    # Also grab the source -> alias mapping for redirect planning
                    pairs = re.findall(r"\('(\d+)','([^']+)','([^']+)','(?:und|en)'\)", line)
                    for pid, source, alias in pairs:
                        if not alias.startswith(('taxonomy/', 'node/', 'user/')):
                            content_map.append({"type": "URL Alias", "value": "/" + alias, "source": "DB (alias)"})
    except Exception as e:
        print(f"Read Error: {e}")

    return content_map


def map_assets():
    print("MAPPING STATIC ASSETS (Images/PDFs)...")
    assets = []
    for root, dirs, files in os.walk(LAB_ROOT):
        for f in files:
            if f.lower().endswith(('.jpg', '.jpeg', '.png', '.pdf', '.gif', '.webp', '.svg')):
                # Get path relative to the public_html equivalent
                rel_path = os.path.relpath(os.path.join(root, f), LAB_ROOT)
                size = 0
                try:
                    size = os.path.getsize(os.path.join(root, f))
                except Exception:
                    pass
                assets.append({"type": "Asset", "value": rel_path, "source": "File", "size": size})
    return assets


def generate_map():
    all_data = []

    # 1. Parse DB
    dumps = find_sql_dump()
    if dumps:
        print(f"   Found {len(dumps)} SQL dump(s):")
        for d in dumps:
            sz = os.path.getsize(d)
            sz_label = f"{sz / (1024*1024):.1f} MB" if sz > 1024*1024 else f"{sz / 1024:.1f} KB"
            print(f"      {os.path.basename(d)} ({sz_label})")

        # Usually the largest SQL file is the main DB
        main_db = sorted(dumps, key=lambda x: os.path.getsize(x), reverse=True)[0]
        db_entries = parse_content_from_sql(main_db)
        # Add size field for consistency
        for entry in db_entries:
            entry["size"] = 0
        all_data.extend(db_entries)
        print(f"   Extracted {len(db_entries)} entries from DB")
    else:
        print("   No SQL database found to parse.")

    # 2. Parse Files
    assets = map_assets()
    # Normalize to same schema
    for a in assets:
        pass  # Already has all fields
    all_data.extend(assets)

    # 3. Save (sanitize any bad Unicode from filenames)
    for entry in all_data:
        entry["value"] = entry["value"].encode('utf-8', errors='replace').decode('utf-8')

    with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=["type", "value", "source", "size"])
        writer.writeheader()
        writer.writerows(all_data)

    # 4. Summary
    page_titles = [x for x in all_data if x["type"] == "Page Title"]
    url_aliases = [x for x in all_data if x["type"] == "URL Alias"]
    asset_files = [x for x in all_data if x["type"] == "Asset"]

    print(f"\nSITE MAP COMPLETE: {OUTPUT_CSV}")
    print(f"   Page Titles Found:  {len(page_titles):,}")
    print(f"   URL Aliases Found:  {len(url_aliases):,}")
    print(f"   Static Assets:      {len(asset_files):,}")
    print(f"   TOTAL NODES MAPPED: {len(all_data):,}")
    print(f"\n   Use this CSV to build 301 Redirects and seed your new Supabase database.")


if __name__ == "__main__":
    generate_map()
