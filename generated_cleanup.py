```python
import json
import os
import argparse
import logging

# Set up logging
logging.basicConfig(filename='cleanup_log.txt', level=logging.INFO, format='%(asctime)s - %(message)s')

def apply_safety_rules(duplicate_pairs, dry_run):
    for pair in duplicate_pairs:
        original = pair['original']
        duplicate = pair['duplicate']

        # Check if either file has 'Final' or 'Tax' in its name
        has_final_or_tax = any(keyword in os.path.basename(file) for file in (original, duplicate) for keyword in ('Final', 'Tax'))

        # Find the oldest file
        oldest_file = min((original, duplicate), key=os.path.getmtime)

        # Determine which file to keep
        keep_original = oldest_file == original or has_final_or_tax and 'Final' in os.path.basename(original)
        keep_duplicate = oldest_file == duplicate or has_final_or_tax and 'Final' in os.path.basename(duplicate)

        # Log and delete the duplicate file if not in dry-run mode
        if keep_original and keep_duplicate:
            logging.info(f"Keeping both {original} and {duplicate} due to 'Final' or 'Tax' in name")
        elif keep_original:
            logging.info(f"Keeping {original}, deleting {duplicate}")
            if not dry_run:
                os.remove(duplicate)
        elif keep_duplicate:
            logging.info(f"Keeping {duplicate}, deleting {original}")
            if not dry_run:
                os.remove(original)

def main():
    parser = argparse.ArgumentParser(description='Cleanup duplicate files')
    parser.add_argument('--dry-run', action='store_true', default=True, help='Only print what would be deleted')
    args = parser.parse_args()

    with open('nas_audit_report.json') as f:
        data = json.load(f)

    duplicate_pairs = data['duplicates']

    apply_safety_rules(duplicate_pairs, args.dry_run)

if __name__ == '__main__':
    main()
```