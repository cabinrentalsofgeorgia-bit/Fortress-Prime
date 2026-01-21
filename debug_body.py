import os
import sys

SQL_FILE = os.path.expanduser("~/fortress-prime/backup-1.18.2026_21-12-59_cabinre/mysql/cabinre_drupal7.sql")

def sql_value_parser(line):
    try:
        start = line.find("VALUES (") + 8
        if start < 8: return
    except: return

    in_quote = False
    escape = False
    waiting_for_row_start = False
    current_val = []
    current_row = []
    
    for char in line[start:]:
        if waiting_for_row_start:
            if char == '(':
                waiting_for_row_start = False
                current_val = []
            continue
        if escape:
            current_val.append(char)
            escape = False
            continue
        if char == '\\':
            escape = True
            continue
        if char == "'":
            in_quote = not in_quote
            continue
        if char == ',' and not in_quote:
            val = "".join(current_val).strip()
            if val.startswith("'") and val.endswith("'"): val = val[1:-1]
            current_row.append(val)
            current_val = []
            continue
        if char == ')' and not in_quote:
            val = "".join(current_val).strip()
            if val.startswith("'") and val.endswith("'"): val = val[1:-1]
            current_row.append(val)
            yield current_row
            return # STOP AFTER 1 ROW

with open(SQL_FILE, 'r', encoding='utf-8', errors='replace') as f:
    for line in f:
        if "INSERT INTO `field_data_body`" in line:
            print("[*] Found Content Table. Inspecting first row...")
            for row in sql_value_parser(line):
                print(f"--- ROW LENGTH: {len(row)} ---")
                for i, col in enumerate(row):
                    preview = col[:50].replace('\n', ' ')
                    print(f"Column [{i}]: {preview}")
            break
