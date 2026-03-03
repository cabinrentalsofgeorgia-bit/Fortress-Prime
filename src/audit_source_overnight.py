import os, hashlib, time, json, signal, sys

# CONFIG
NAS_ROOT = "/mnt/vol1_source"
OUTPUT_REPORT = os.path.expanduser("~/Fortress-Prime/source_audit_report.json")
MAX_FILE_SIZE = 5 * 1024 * 1024 * 1024 # 5GB Limit
TIMEOUT_SEC = 20

class TimeoutError(Exception): pass
def timeout_handler(signum, frame): raise TimeoutError

def get_hash(path):
    sha = hashlib.sha256()
    signal.signal(signal.SIGALRM, timeout_handler)
    try:
        if os.path.getsize(path) > MAX_FILE_SIZE: return f"SKIPPED_LARGE"
        with open(path, 'rb') as f:
            while True:
                signal.alarm(TIMEOUT_SEC)
                data = f.read(65536)
                signal.alarm(0)
                if not data: break
                sha.update(data)
        return sha.hexdigest()
    except: return "ERROR"
    finally: signal.alarm(0)

def scan():
    print(f"🌙 NIGHT SCAN STARTED: {NAS_ROOT}")
    files = {}
    count = 0
    start = time.time()
    for root, dirs, f_names in os.walk(NAS_ROOT):
        if "@eaDir" in root or ".Recycle" in root: continue
        for name in f_names:
            path = os.path.join(root, name)
            try:
                h = get_hash(path)
                files[path] = {"hash": h, "size": os.path.getsize(path)}
                count += 1
                if count % 100 == 0:
                    print(f"...{count} files ({int(time.time()-start)}s)... {name}")
                    sys.stdout.flush()
            except: pass
    
    with open(OUTPUT_REPORT, 'w') as f: json.dump({"files": files}, f)
    print(f"✅ COMPLETE. Scanned {count} files.")

if __name__ == "__main__": scan()
