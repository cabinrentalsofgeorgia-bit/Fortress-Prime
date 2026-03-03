import json
import os
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from datetime import datetime
import sys

# --- CONFIG ---
INPUT_REPORT = os.path.expanduser("~/Fortress-Prime/source_audit_clean.json")
OUTPUT_PDF = os.path.expanduser("~/Fortress-Prime/Fortress_Vol1_Clean_Atlas.pdf")
MAX_FILES_PER_FOLDER = 50  # Prevent 300k emails from crashing the PDF

def draw_header(c, page_num, section_name):
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, 750, f"Fortress Volume 1 Audit - {section_name}")
    c.setFont("Helvetica", 9)
    c.drawRightString(550, 750, f"Page {page_num}")
    c.line(50, 745, 560, 745)

def shorten_path(path):
    # Converts /mnt/vol1_source/Business/CROG -> /Business/CROG
    return path.replace("/mnt/vol1_source", "")

def generate_pdf():
    print(f"📖 LOADING MASSIVE DATASET: {INPUT_REPORT}")
    if not os.path.exists(INPUT_REPORT):
        print("❌ Report missing.")
        return

    # Load Data
    try:
        with open(INPUT_REPORT, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ Failed to load JSON: {e}")
        return

    files_dict = data.get("files", {})
    total_files = len(files_dict)
    print(f"🌳 ORGANIZING {total_files:,} FILES INTO TREE STRUCTURE...")

    # Build Tree in Memory
    tree = {}
    for path, meta in files_dict.items():
        clean_path = shorten_path(path)
        parts = clean_path.strip("/").split("/")
        
        current = tree
        for part in parts[:-1]: # Folders
            if part not in current:
                current[part] = {}
            current = current[part]
            if "__files__" not in current:
                current["__files__"] = []
        
        # Add file to the current folder
        filename = parts[-1]
        if "__files__" not in current:
             current["__files__"] = []
        current["__files__"].append(filename)

    print("📄 RENDERING PDF (This will take time)...")
    
    c = canvas.Canvas(OUTPUT_PDF, pagesize=LETTER)
    width, height = LETTER
    y = 700
    page_num = 1
    current_section = "Overview"

    # --- COVER PAGE ---
    c.setFont("Helvetica-Bold", 24)
    c.drawString(50, 600, "FORTRESS VOLUME 1: MASTER ATLAS")
    c.setFont("Helvetica", 14)
    c.drawString(50, 570, f"Total Indexed items: {total_files:,}")
    c.drawString(50, 550, f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    c.showPage()
    page_num += 1

    # --- RECURSIVE DRAW ---
    c.setFont("Courier", 9)
    
    def draw_node(node, level, parent_path):
        nonlocal y, page_num, current_section
        
        # Sort: Folders first, then Files
        keys = sorted(node.keys())
        subfolders = [k for k in keys if k != "__files__"]
        files = sorted(node.get("__files__", []))
        
        # Draw Folders
        for folder in subfolders:
            if y < 50:
                c.showPage()
                page_num += 1
                y = 720
                draw_header(c, page_num, current_section)
                c.setFont("Courier", 9)

            # Draw Folder Name
            indent = level * 15
            c.setFont("Helvetica-Bold", 9)
            c.setFillColor(colors.darkblue)
            c.drawString(50 + indent, y, f"📁 {folder}/")
            c.setFillColor(colors.black)
            y -= 12
            
            # Recurse
            draw_node(node[folder], level + 1, f"{parent_path}/{folder}")

        # Draw Files (With Limits)
        c.setFont("Courier", 9)
        file_count = len(files)
        display_limit = MAX_FILES_PER_FOLDER
        
        for i, filename in enumerate(files):
            if i >= display_limit:
                indent = (level + 1) * 15
                c.setFillColor(colors.gray)
                c.drawString(50 + indent, y, f"... and {file_count - display_limit} more files ...")
                c.setFillColor(colors.black)
                y -= 12
                break

            if y < 50:
                c.showPage()
                page_num += 1
                y = 720
                draw_header(c, page_num, current_section)
                c.setFont("Courier", 9)
            
            indent = (level + 1) * 15
            c.drawString(50 + indent, y, f"📄 {filename}")
            y -= 12

    # Start Drawing from Root
    draw_header(c, page_num, "Full Directory Map")
    draw_node(tree, 0, "")
    
    c.save()
    print(f"✅ ATLAS GENERATED: {OUTPUT_PDF}")

if __name__ == "__main__":
    generate_pdf()
