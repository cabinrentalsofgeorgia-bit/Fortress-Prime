import os
import csv
import io
import requests
import psycopg2
import sys

# --- CONFIGURATION ---
SQL_FILE = os.path.expanduser("~/fortress-prime/backup-1.18.2026_21-12-59_cabinre/mysql/cabinre_drupal7.sql")
DOMAIN_ROOT = "https://cabin-rentals-of-georgia.com/"

DB_HOST = "localhost"
DB_NAME = "fortress_db"
DB_USER = "miner_bot"
DB_PASS = "190AntiochCemeteryRD!!!"
WORKER_IP = "192.168.0.104"
OLLAMA_EMBED = f"http://{WORKER_IP}:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text"

# --- MEMORY MAPS ---
url_map = {}
title_map = {}
type_map = {}
redirect_map = {}

def get_embedding(text):
    if not text or len(text) < 10: return [0.0] * 768
    try:
        response = requests.post(OLLAMA_EMBED, json={"model": EMBED_MODEL, "prompt": text[:4000]}, timeout=5)
        if response.status_code == 200:
            return response.json()["embedding"]
    except: pass
    return [0.0] * 768

def run_reconstruction():
    print(f"[*] TITAN v17: Enterprise CSV Kernel on {SQL_FILE}...")
    
    try:
        conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
        cursor = conn.cursor()
    except Exception as e:
        print(f"[!] DATABASE ERROR: {e}")
        return

    # --- PASS 1: MAP STRUCTURE ---
    print("    [Phase 1] Mapping Links...")
    # (Mapping logic omitted for brevity as it works reliably, keeping it minimal for success)
    # We will use a quick regex just for the map to keep this part fast
    import re
    with open(SQL_FILE, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            if not line.startswith("INSERT INTO"): continue
            if "`url_alias`" in line:
                matches = re.findall(r"'node/(\d+)',\s*'([^']+)'", line)
                for nid, alias in matches: url_map[f"node/{nid}"] = alias
            elif "`node`" in line:
                matches = re.findall(r"\((\d+),\d+,'([^']+)',\s*'[^']+',\s*'([^']+)'", line)
                for nid, ntype, title in matches:
                    title_map[nid] = title
                    type_map[nid] = ntype
            elif "`redirect`" in line:
                matches = re.findall(r"'(node/\d+)'.*?'(http[^']+|[^']+\.html|[^']+\.php)'", line)
                matches_internal = re.findall(r"'(node/\d+)'.*?'(node/[^']+)'", line)
                for s, d in (matches + matches_internal):
                    if s not in redirect_map: redirect_map[s] = []
                    redirect_map[s].append(d)

    print(f"    -> Mapped {len(url_map)} URLs")

    # --- PASS 2: THE CSV KERNEL ---
    print("    [Phase 2] Decoding Content via CSV Engine...")
    count = 0
    
    with open(SQL_FILE, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            if "INSERT INTO `field_data_body`" in line:
                
                # 1. PREPARE THE LINE FOR CSV PARSING
                # Strip the SQL Command: INSERT INTO ... VALUES (
                start_marker = "VALUES ("
                idx = line.find(start_marker)
                if idx == -1: continue
                
                clean_line = line[idx + len(start_marker):].strip()
                if clean_line.endswith(");"): clean_line = clean_line[:-2]
                
                # 2. THE NUCLEAR OPTION: CSV READER
                # We tell Python: "This is a CSV file where the quote is ' and the escape is \" "
                # It handles ALL complexity automatically.
                reader = csv.reader(io.StringIO(clean_line), delimiter=',', quotechar="'", escapechar='\\', skipinitialspace=True)
                
                try:
                    for all_values in reader:
                        # The CSV reader returns ONE giant list of values.
                        # We must detect the "Stride" (how many columns per row).
                        # We know column 0 is 'node' (or whatever entity type).
                        
                        # Let's find the stride dynamically by looking for the second 'node'
                        # Or we assume 8 columns based on previous X-Rays.
                        
                        # Data stream looks like: ['node', 'bundle', '0', 'ID', 'Rev', 'und', '0', 'BODY', 'format', 'node'...]
                        # The pattern repeats.
                        
                        data = all_values
                        if len(data) < 8: continue
                        
                        # Find indices where value is 'node' (start of a row)
                        starts = [i for i, x in enumerate(data) if x == 'node']
                        if not starts: continue
                        
                        # Calculate stride
                        stride = 9 # Default guess
                        if len(starts) > 1:
                            stride = starts[1] - starts[0]
                        
                        print(f"    [DEBUG] Detected Row Stride: {stride} columns.")
                        
                        # PROCESS CHUNKS
                        for i in range(0, len(data), stride):
                            row = data[i:i+stride]
                            if len(row) < 8: continue
                            
                            # ID is at index 3
                            nid = row[3]
                            if not nid.isdigit(): continue
                            
                            # Body is at index 7
                            body_text = row[7]
                            
                            if len(body_text) < 20: 
                                # print(f"    [DEBUG] ID {nid}: Content too short.")
                                continue
                            
                            # 3. BUILD
                            title = title_map.get(nid, "Unknown Page")
                            node_type = type_map.get(nid, "page")
                            
                            type_label = "WEBSITE PAGE"
                            if node_type == 'activity': type_label = "THINGS TO DO / ACTIVITY"
                            elif node_type == 'cabin': type_label = "CABIN RENTAL PROPERTY"
                            elif node_type == 'blog': type_label = "BLOG POST"
                            elif node_type == 'micro_site': type_label = "SPECIAL LANDING PAGE"
                            
                            node_path = f"node/{nid}"
                            slug = url_map.get(node_path, node_path)
                            full_url = DOMAIN_ROOT + slug
                            
                            inbound_links = redirect_map.get(node_path, [])
                            inbound_text = "\n".join([f"- {i}" for i in inbound_links])
                            
                            full_record = f"TYPE: {type_label}\nURL: {full_url}\nTITLE: {title}\n---\nCONTENT:\n{body_text[:12000]}"
                            
                            # 4. SAVE (VERBOSE ERROR CATCHING)
                            try:
                                # IGNORE EXISTENCE CHECK FOR DEBUGGING - FORCE INSERT ATTEMPT
                                vector = get_embedding(full_record)
                                
                                cursor.execute("""
                                    INSERT INTO market_intel (source_file, content, embedding, sender, subject_line, sent_at)
                                    VALUES (%s, %s, %s, %s, %s, NOW())
                                    ON CONFLICT DO NOTHING
                                """, (f"NODE_{nid}", full_record, vector, "Drupal Archive", f"[{node_type.upper()}] {title}",))
                                conn.commit()
                                
                                count += 1
                                if count % 10 == 0:
                                    print(f" -> Rebuilt {type_label}: {title[:30]}...")
                                    
                            except Exception as db_err:
                                print(f"    [!] SAVE ERROR ID {nid}: {db_err}")
                                conn.rollback()
                                
                except Exception as csv_err:
                    print(f"    [!] CSV PARSE ERROR: {csv_err}")

    print(f"\n[+] TITAN V17 COMPLETE. Reconstructed {count} pages.")
    conn.close()

if __name__ == "__main__":
    run_reconstruction()
