import re
import os
import csv

LAB_ROOT = "/mnt/fortress_nas/Enterprise_War_Room/Web_Lab/Exploded"
OUTPUT_CSV = "/mnt/fortress_nas/Enterprise_War_Room/Web_Lab/website_full_content.csv"

def find_sql_dump():
    """Find the LARGEST .sql file — that's the main Drupal database."""
    all_sql = []
    for root, dirs, files in os.walk(LAB_ROOT):
        for f in files:
            if f.endswith(".sql"):
                full = os.path.join(root, f)
                try:
                    all_sql.append((full, os.path.getsize(full)))
                except Exception:
                    pass
    if not all_sql:
        return None
    # Return the biggest one
    all_sql.sort(key=lambda x: x[1], reverse=True)
    return all_sql[0][0]

def strip_html(text):
    """Remove HTML tags for clean text output."""
    clean = re.sub(r'<[^>]+>', ' ', text)
    clean = re.sub(r'&\w+;', ' ', clean)
    clean = re.sub(r'&#\d+;', ' ', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean

def extract_body():
    sql_file = find_sql_dump()
    if not sql_file:
        print("No SQL dump found.")
        return
    print(f"📖 EXTRACTING PAGE CONTENT FROM: {os.path.basename(sql_file)}")
    
    data = []
    
    in_body_insert = False
    
    with open(sql_file, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            # Only process INSERT INTO field_data_body lines
            if 'INSERT INTO `field_data_body`' in line:
                # Each value tuple: ('node','cabin',0,ID,REV,'und',0,'BODY_HTML','SUMMARY','FORMAT')
                # Split on '),(' to get individual rows
                # body_value is the 8th column (index 7) — contains the HTML content
                tuples = re.findall(r"\('node','([^']*)',\d+,(\d+),\d+,'[^']*',\d+,'((?:[^'\\]|\\.)*?)','(?:[^'\\]|\\.)*?','[^']*'\)", line)
                for bundle, entity_id, body_html in tuples:
                    clean = strip_html(body_html)
                    if len(clean) > 50:
                        data.append({
                            "content_snippet": clean[:500],
                            "full_length": len(clean),
                            "bundle": bundle,
                            "entity_id": entity_id
                        })
                
    print(f"✅ Found {len(data):,} content blocks. Saving...")
    with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=["bundle", "entity_id", "content_snippet", "full_length"])
        writer.writeheader()
        writer.writerows(data)
    
    # Show a few samples
    if data:
        print(f"\n--- SAMPLE CONTENT ---")
        for d in data[:5]:
            print(f"   ({d['full_length']:,} chars) {d['content_snippet'][:120]}...")
        print(f"   ...and {len(data)-5} more")

if __name__ == "__main__":
    extract_body()
