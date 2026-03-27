import os
import ftplib
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [VANGUARD EXTRACTION] - %(message)s')

# --- TARGET DIRECTORIES ---
NAS_DIR = "/mnt/vol1_source/Backups/CPanel_Full"
FTP_HOST = "mail.cabin-rentals-of-georgia.com"
FTP_USER = "cabinre" # Your primary cPanel username
FTP_PASS = "nLDYZLYDwjNwU" # Your primary cPanel password

def execute_extraction():
    os.makedirs(NAS_DIR, exist_ok=True)
    logging.info(f"Connecting to legacy host: {FTP_HOST}")

    try:
        # Establish connection to the legacy host
        ftp = ftplib.FTP(FTP_HOST)
        ftp.login(user=FTP_USER, passwd=FTP_PASS)
        logging.info("Perimeter breached. Scanning for backup payloads...")

        # Locate the massive cPanel backup file
        files = ftp.nlst()
        backup_files = [f for f in files if f.startswith("backup-") and f.endswith(".tar.gz")]

        if not backup_files:
            logging.error("No backup file found yet. The legacy server is likely still compiling it.")
            ftp.quit()
            return

        # Target the most recently generated backup
        target_file = sorted(backup_files)[-1]
        local_path = os.path.join(NAS_DIR, target_file)

        logging.info(f"Target locked: {target_file}.")
        logging.info(f"Initiating direct stream to NAS: {local_path}. Stand by...")

        # Stream the file directly to the Synology NAS
        with open(local_path, "wb") as f:
            ftp.retrbinary(f"RETR {target_file}", f.write)

        logging.info("Extraction complete. All legacy data secured on local hardware.")
        ftp.quit()

    except Exception as e:
        logging.error(f"Extraction failed: {e}")

if __name__ == "__main__":
    execute_extraction()
