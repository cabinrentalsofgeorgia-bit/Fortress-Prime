import argparse
import glob
import logging
import os
import tarfile
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [VANGUARD UNPACKER] - %(message)s")

ARCHIVE_DIR = "/mnt/vol1_source/Backups/CPanel_Full"
CLEAN_DATA_DIR = "/mnt/vol1_source/Backups/CPanel_Extracted"


def _iter_target_members(archive: tarfile.TarFile):
    for member in archive:
        name = member.name
        lower = name.lower()

        if "/mysql/" in lower:
            yield member
            continue
        if lower.startswith("backup/config/mysql"):
            yield member
            continue
        if lower.startswith("backup/homedir/") and lower.endswith(".sql"):
            yield member
            continue
        if lower.startswith("backup/mysql/"):
            yield member
            continue


def _safe_extract_member(archive: tarfile.TarFile, member: tarfile.TarInfo, dest_dir: Path) -> bool:
    target_path = dest_dir / member.name
    resolved_target = target_path.resolve()
    resolved_dest = dest_dir.resolve()
    if not str(resolved_target).startswith(str(resolved_dest)):
        logging.warning("Skipping suspicious archive member: %s", member.name)
        return False
    archive.extract(member, path=dest_dir)
    return True


def unpack_payload(source: str | None = None) -> None:
    os.makedirs(CLEAN_DATA_DIR, exist_ok=True)
    dest_dir = Path(CLEAN_DATA_DIR)

    logging.info("Scanning NAS for the latest legacy payload...")
    if source:
        latest_archive = source
        if not os.path.isfile(latest_archive):
            logging.error("Provided source file does not exist: %s", latest_archive)
            return
    else:
        files = glob.glob(os.path.join(ARCHIVE_DIR, "*.tar.gz"))
        if not files:
            logging.error("No backup payload found on the NAS yet.")
            return
        latest_archive = max(files, key=os.path.getctime)

    logging.info("Target locked: %s", os.path.basename(latest_archive))
    logging.info("Initiating high-speed extraction. Stripping away legacy cPanel junk...")
    logging.info("Isolating raw MySQL database files...")

    try:
        extracted = 0
        with tarfile.open(latest_archive, "r:gz") as archive:
            for member in _iter_target_members(archive):
                if _safe_extract_member(archive, member, dest_dir):
                    extracted += 1

        if extracted == 0:
            logging.error("Extraction failed. No recognized DB paths found in archive layout.")
            return

        logging.info("✔ Success. Extracted %d DB-related entries to: %s", extracted, CLEAN_DATA_DIR)
        logging.info("The Fortress is ready to ingest.")
    except (tarfile.TarError, OSError) as exc:
        logging.error("Extraction failed. The file may still be downloading/corrupt: %s", exc)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract DB payload from cPanel tar archive.")
    parser.add_argument("--source", help="Absolute path to a specific .tar.gz payload (optional).")
    args = parser.parse_args()
    unpack_payload(source=args.source)
