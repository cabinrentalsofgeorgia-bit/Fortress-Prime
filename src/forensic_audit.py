import os
import hashlib
import time
import datetime
import json
import signal

# --- CONFIGURATION ---
NAS_ROOT = "/mnt/fortress_nas"
OUTPUT_REPORT = os.path.expanduser("~/Fortress-Prime/nas_audit_report.json")
ERROR_LOG = os.path.expanduser("~/Fortress-Prime/audit_errors.log")
CRASH_DATE = datetime.datetime(2025, 1, 1).timestamp()
MAX_FILE_SIZE_HASH = 5 * 1024 * 1024 * 1024  # Skip hashing files > 5GB
TIMEOUT_SECONDS = 10  # Seconds allowed per read operation

class TimeoutError(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutError

def calculate_hash(filepath, block_size=65536):
    """Hashes file with a strict timeout watchdog."""
    sha256 = hashlib.sha256()
    # Set the signal handler for timeouts
    signal.signal(signal.SIGALRM, timeout_handler)

    try:
        size = os.path.getsize(filepath)
        if size > MAX_FILE_SIZE_HASH:
            return f"SKIPPED_TOO_LARGE_{size}"

        with open(filepath, 'rb') as f:
            while True:
                signal.alarm(TIMEOUT_SECONDS) # Start watchdog
                data = f.read(block_size)
                signal.alarm(0) # Reset watchdog

                if not data:
                    break
                sha256.update(data)
        return sha256.hexdigest()
    except TimeoutError:
        print(f"   ⚠️ TIMEOUT (NFS STALL): {filepath}")
        return "ERROR_TIMEOUT"
    except Exception as e:
        print(f"   ⚠️ READ ERROR: {filepath} ({e})")
        return f"ERROR_{e}"
    finally:
        signal.alarm(0) # Ensure alarm is off

def audit_drive():
    print(f"🕵️ STARTING ROBUST FORENSIC AUDIT: {NAS_ROOT}")
    print(f"   (Timeout: {TIMEOUT_SECONDS}s | Max Hash Size: {MAX_FILE_SIZE_HASH/1024**3:.1f}GB)")

    file_registry = {}
    duplicates = []
    errors = []

    count = 0
    start_time = time.time()

    for root, dirs, files in os.walk(NAS_ROOT):
        if ".cache" in root or ".git" in root:
            continue

        for name in files:
            filepath = os.path.join(root, name)

            # Metadata Check (Fast)
            try:
                stats = os.stat(filepath)
            except:
                continue

            # Content Check (Slow - Protected by Timeout)
            file_hash = calculate_hash(filepath)

            if "ERROR" in file_hash:
                errors.append(filepath)
                continue

            # Logic
            is_pre_crash = stats.st_mtime < CRASH_DATE

            if file_hash in file_registry and "SKIPPED" not in file_hash:
                original = file_registry[file_hash]['path']
                print(f"   ♻️ DUPLICATE: {name} (Matches {os.path.basename(original)})")
                duplicates.append({
                    "original": original,
                    "duplicate": filepath,
                    "size": stats.st_size
                })
            else:
                file_registry[file_hash] = {
                    "path": filepath,
                    "size": stats.st_size,
                    "created": time.ctime(stats.st_ctime),
                    "pre_crash": is_pre_crash
                }

            count += 1
            if count % 50 == 0:
                print(f"   ...Scanned {count} files (Time: {int(time.time()-start_time)}s)...")

    # Save Report
    with open(OUTPUT_REPORT, 'w') as f:
        json.dump({"files": file_registry, "duplicates": duplicates, "errors": errors}, f, indent=4)

    print("-" * 40)
    print(f"✅ AUDIT COMPLETE.")
    print(f"   Files Scanned: {count}")
    print(f"   Duplicates: {len(duplicates)}")
    print(f"   Errors/Timeouts: {len(errors)}")
    print(f"   Report: {OUTPUT_REPORT}")

if __name__ == "__main__":
    audit_drive()
