"""
STREAMLINE TOKEN RENEWER — Automatic Credential Rotation
==========================================================
Fortress Prime | Cabin Rentals of Georgia

Calls Streamline's RenewExpiredToken method before the current token
expires (2026-03-11). On success, updates .env with the new credentials.

Should be run weekly via cron starting ~2 weeks before expiration.

Usage:
    python3 src/bridges/token_renewer.py             # attempt renewal
    python3 src/bridges/token_renewer.py --check      # just check expiration

Cron (weekly, Mondays at 04:00 AM — starting Feb 23):
    0 4 * * 1 /usr/bin/python3 /home/admin/Fortress-Prime/src/bridges/token_renewer.py
"""

import os
import sys
import re
import json
import glob
import logging
import argparse
import base64
import requests
from datetime import datetime
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ENV_PATH = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
API_URL = "https://web.streamlinevrs.com/api/json"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = "/mnt/fortress_nas/fortress_data/ai_brain/logs"
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("TokenRenewer")
logger.setLevel(logging.INFO)

_fh = logging.FileHandler(os.path.join(LOG_DIR, "token_renewer.log"))
_fh.setFormatter(logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))
logger.addHandler(_fh)

_ch = logging.StreamHandler()
_ch.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
logger.addHandler(_ch)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _read_env_credentials():
    """Read current Streamline credentials from .env."""
    if not os.path.exists(ENV_PATH):
        logger.error(f"[RENEW] .env not found at {ENV_PATH}")
        return None, None, None

    with open(ENV_PATH, "r") as f:
        content = f.read()

    # Match both quoted and unquoted formats
    key_match = re.search(r'STREAMLINE_TOKEN_KEY[= ]+"?([^"\n]+)"?', content)
    secret_match = re.search(r'STREAMLINE_TOKEN_SECRET[= ]+"?([^"\n]+)"?', content)
    exp_match = re.search(r'STREAMLINE_TOKEN_EXPIRATION[= ]+"?([^"\n]+)"?', content)

    key = key_match.group(1).strip() if key_match else ""
    secret = secret_match.group(1).strip() if secret_match else ""
    expiration = exp_match.group(1).strip() if exp_match else ""

    return key, secret, expiration


def _call_streamline(method: str, key: str, secret: str, extra: dict = None) -> dict:
    """Call the Streamline Legacy RPC API."""
    params = {"token_key": key, "token_secret": secret}
    if extra:
        params.update(extra)
    payload = {"methodName": method, "params": params}
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    r = requests.post(API_URL, json=payload, headers=headers, timeout=30)
    return r.json()


def _derive_backup_key() -> bytes:
    """Derive a Fernet key from the FGP SECRET_KEY for encrypted .env backups."""
    secret = os.getenv("SECRET_KEY", "fortress_fallback_secret").encode()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'fortress_env_backup_salt',
        iterations=480000,
    )
    return base64.urlsafe_b64encode(kdf.derive(secret))


def _secure_env_backup(env_path: str, timestamp: str):
    """Encrypt .env backup and purge any legacy plaintext backup files."""
    backup_path = f"{env_path}.pre_renew_{timestamp}.enc"

    with open(env_path, 'rb') as f:
        env_data = f.read()

    fernet = Fernet(_derive_backup_key())
    encrypted_data = fernet.encrypt(env_data)

    with open(backup_path, 'wb') as f:
        f.write(encrypted_data)
    os.chmod(backup_path, 0o600)
    logger.info(f"[RENEW] .env backed up (encrypted) to {backup_path}")

    purged = 0
    for legacy_file in glob.glob(f"{env_path}.pre_renew_*") + glob.glob(f"{env_path}.backup.*"):
        if not legacy_file.endswith('.enc'):
            os.remove(legacy_file)
            logger.info(f"[SECURE ENCLAVE] Shredded legacy plaintext backup: {legacy_file}")
            purged += 1
    if purged:
        logger.info(f"[SECURE ENCLAVE] Purged {purged} legacy plaintext backup(s)")


def _update_env(key: str, value: str):
    """Update a single key in the .env file."""
    with open(ENV_PATH, "r") as f:
        content = f.read()

    # Match the key line (handles both quoted and unquoted)
    pattern = rf'^{re.escape(key)}=.*$'
    replacement = f'{key}={value}'

    new_content, count = re.subn(pattern, replacement, content, flags=re.MULTILINE)

    if count == 0:
        # Key doesn't exist — append it
        new_content = content.rstrip() + f"\n{replacement}\n"

    with open(ENV_PATH, "w") as f:
        f.write(new_content)


# ---------------------------------------------------------------------------
# Check Expiration
# ---------------------------------------------------------------------------
def check_expiration():
    """Check if the current token is near expiration."""
    key, secret, exp_str = _read_env_credentials()

    if not key or not secret:
        logger.error("[RENEW] Missing credentials in .env")
        return {"status": "ERROR", "reason": "Missing credentials"}

    # Check expiration from .env
    days_remaining = None
    if exp_str:
        try:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            days_remaining = (exp_date - datetime.now().date()).days
        except ValueError:
            pass

    # Also verify with API
    try:
        result = _call_streamline("GetTokenExpiration", key, secret)
        api_exp = result.get("data", {}).get("expiration", "")

        if api_exp:
            try:
                api_date = datetime.strptime(api_exp, "%m/%d/%Y").date()
                days_remaining = (api_date - datetime.now().date()).days
                exp_str = api_date.isoformat()
            except ValueError:
                pass
    except Exception as e:
        logger.warning(f"[RENEW] Could not verify with API: {e}")

    info = {
        "token_key": f"{key[:8]}...{key[-4:]}",
        "expiration": exp_str,
        "days_remaining": days_remaining,
    }

    if days_remaining is not None:
        if days_remaining <= 0:
            info["status"] = "EXPIRED"
            logger.error(f"[RENEW] Token EXPIRED {abs(days_remaining)} days ago!")
        elif days_remaining <= 7:
            info["status"] = "CRITICAL"
            logger.warning(f"[RENEW] Token expires in {days_remaining} days — RENEW NOW")
        elif days_remaining <= 14:
            info["status"] = "WARNING"
            logger.warning(f"[RENEW] Token expires in {days_remaining} days")
        else:
            info["status"] = "OK"
            logger.info(f"[RENEW] Token valid for {days_remaining} more days (expires {exp_str})")
    else:
        info["status"] = "UNKNOWN"

    return info


# ---------------------------------------------------------------------------
# Renew Token
# ---------------------------------------------------------------------------
def renew_token():
    """
    Attempt to renew the Streamline API token.

    Calls RenewExpiredToken with the current credentials.
    On success, updates .env with the new key/secret/expiration.
    """
    logger.info("[RENEW] Starting token renewal protocol...")

    key, secret, _ = _read_env_credentials()
    if not key or not secret:
        logger.error("[RENEW] Missing credentials — cannot renew")
        return {"status": "FAILED", "reason": "Missing credentials"}

    logger.info(f"[RENEW] Current token: {key[:8]}...{key[-4:]}")

    # FORTRESS PROTOCOL: Encrypted .env backup before modification
    try:
        _secure_env_backup(ENV_PATH, datetime.now().strftime('%Y%m%d_%H%M%S'))
    except Exception as e:
        logger.warning(f"[RENEW] Encrypted backup failed: {e}")

    # Call the renewal endpoint
    try:
        result = _call_streamline("RenewExpiredToken", key, secret)
    except Exception as e:
        logger.error(f"[RENEW] API call failed: {e}")
        return {"status": "FAILED", "reason": str(e)}

    # Check for API errors
    status = result.get("status", {})
    if status.get("code"):
        code = status["code"]
        desc = status.get("description", "Unknown error")
        logger.error(f"[RENEW] API error {code}: {desc}")

        if code == "E0014":
            logger.info("[RENEW] RenewExpiredToken not allowed for this token type.")
            logger.info("[RENEW] Manual renewal required via Streamline Partner Portal.")
        elif code == "E0012":
            logger.error("[RENEW] IP blocked — whitelist may have changed.")

        return {"status": "DENIED", "code": code, "description": desc}

    # Parse new credentials
    data = result.get("data", {})
    new_key = data.get("token_key", "")
    new_secret = data.get("token_secret", "")
    new_exp = data.get("token_expiration_date", data.get("expiration", ""))

    if new_key and new_secret:
        logger.info(f"[RENEW] New token acquired: {new_key[:8]}...{new_key[-4:]}")
        logger.info(f"[RENEW] New expiration: {new_exp}")

        # Update .env
        _update_env("STREAMLINE_TOKEN_KEY", new_key)
        _update_env("STREAMLINE_TOKEN_SECRET", new_secret)
        if new_exp:
            # Normalize to YYYY-MM-DD
            try:
                parsed = datetime.strptime(new_exp, "%m/%d/%Y")
                new_exp_iso = parsed.strftime("%Y-%m-%d")
            except ValueError:
                new_exp_iso = new_exp
            _update_env("STREAMLINE_TOKEN_EXPIRATION", new_exp_iso)

        logger.info("[RENEW] .env updated with new credentials.")

        # Verify the new token works
        try:
            verify = _call_streamline("GetTokenExpiration", new_key, new_secret)
            if verify.get("data", {}).get("expiration"):
                logger.info("[RENEW] New token VERIFIED — API responds correctly.")
            else:
                logger.warning("[RENEW] New token saved but verification inconclusive.")
        except Exception:
            logger.warning("[RENEW] Could not verify new token.")

        return {
            "status": "RENEWED",
            "new_key": f"{new_key[:8]}...{new_key[-4:]}",
            "expiration": new_exp,
        }
    else:
        logger.warning(f"[RENEW] API returned success but no new keys: {data}")
        return {"status": "PARTIAL", "data": data}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Streamline Token Renewer")
    parser.add_argument("--check", action="store_true",
                        help="Check expiration only (no renewal)")
    args = parser.parse_args()

    print("=" * 60)
    print("  STREAMLINE TOKEN RENEWAL PROTOCOL")
    print("=" * 60)

    if args.check:
        info = check_expiration()
        print(f"\n  Token:      {info.get('token_key', '?')}")
        print(f"  Expiration: {info.get('expiration', '?')}")
        print(f"  Days left:  {info.get('days_remaining', '?')}")
        print(f"  Status:     {info.get('status', '?')}")
    else:
        # Check first
        info = check_expiration()
        print(f"\n  Current expiration: {info.get('expiration', '?')}")
        print(f"  Days remaining:     {info.get('days_remaining', '?')}")

        if info.get("status") == "OK" and info.get("days_remaining", 0) > 14:
            print(f"\n  Token still valid for {info['days_remaining']} days.")
            print("  Renewal not needed yet. Use --check to monitor.")
        else:
            print(f"\n  Attempting renewal...")
            result = renew_token()
            print(f"\n  Result: {result.get('status', '?')}")
            if result.get("expiration"):
                print(f"  New expiration: {result['expiration']}")
            if result.get("description"):
                print(f"  Message: {result['description']}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
