import json
import os
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from datetime import datetime

# --- CONFIG ---
INPUT_REPORT = os.path.expanduser("~/Fortress-Prime/nas_audit_report.json")
OUTPUT_PDF = os.path.expanduser("~/Fortress-Prime/Fortress_NAS_Audit_Full.pdf")
NAS_ROOT_NAME = "Fortress NAS"

def draw_header(c, page_num):
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, 750, "Fortress Prime - Forensic NAS Audit")
    c.setFont("Helvetica", 9)
    c.drawRightString(550, 750, f"Page {page_num}")
    c.line(50, 745, 560, 745)

def generate_pdf():
    print(f"📄 GENERATING PDF REPORT: {OUTPUT_PDF}")
    
    if not os.path.exists(INPUT_REPORT):
        print("❌ Audit report missing. Please run forensic_audit.py first.")
        return

    with open(INPUT_REPORT, 'r') as f:
        data = json.load(f)

    # Prepare Data
    files = data.get("files", {})
    paths = sorted([meta['path'] for meta in files.values()])
    total_files = len(paths)
    total_size_bytes = sum(meta['size'] for meta in files.values())
    total_size_gb = total_size_bytes / (1024**3)
    
    c = canvas.Canvas(OUTPUT_PDF, pagesize=LETTER)
    width, height = LETTER
    
    # --- PAGE 1: EXECUTIVE SUMMARY ---
    c.setFont("Helvetica-Bold", 24)
    c.drawString(50, 650, "NAS FORENSIC AUDIT")
    c.setFont("Helvetica", 14)
    c.drawString(50, 620, f"Target: {NAS_ROOT_NAME}")
    c.drawString(50, 600, f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, 550, "SUMMARY STATISTICS")
    c.line(50, 545, 250, 545)
    
    c.setFont("Helvetica", 12)
    c.drawString(50, 520, f"• Total Files Indexed: {total_files:,}")
    c.drawString(50, 500, f"• Total Data Volume: {total_size_gb:.2f} GB")
    c.drawString(50, 480, f"• Duplicates Identified: {len(data.get('duplicates', []))}")
    c.drawString(50, 460, f"• Scan Status: COMPLETE")

    c.showPage() # End Cover Page

    # --- PAGES 2+: FILE TREE ---
    y_position = 720
    page_num = 2
    draw_header(c, page_num)
    c.setFont("Courier", 9) # Monospace for alignment

    last_dirs = []
    
    print(f"🌳 Drawing tree for {total_files} files...")

    for path in paths:
        # Check for page break
        if y_position < 50:
            c.showPage()
            page_num += 1
            draw_header(c, page_num)
            y_position = 720
            c.setFont("Courier", 9)

        # Parse Path
        parts = path.strip("/").split("/")
        # Remove the 'mnt/fortress_nas' prefix if strictly mapping content
        if parts[0] == "mnt": parts = parts[1:] 
        if parts[0] == "fortress_nas": parts = parts[1:]

        filename = parts[-1]
        dirs = parts[:-1]
        
        # Determine indentation
        indent = 0
        
        # Check directory changes to print folder headers
        # This logic simplifies the tree to avoid repeating folder names
        current_depth = 0
        for i, d in enumerate(dirs):
            if i >= len(last_dirs) or d != last_dirs[i]:
                # New directory branch
                indent = i * 20
                c.setFont("Helvetica-Bold", 9)
                c.setFillColor(colors.darkblue)
                c.drawString(50 + indent, y_position, f"📁 {d}/")
                c.setFillColor(colors.black)
                y_position -= 12
                # Reset font for files
                c.setFont("Courier", 9)
            current_depth = i

        last_dirs = dirs
        
        # Print File
        file_indent = (len(dirs)) * 20
        c.drawString(50 + file_indent, y_position, f"📄 {filename}")
        y_position -= 12

    c.save()
    print(f"✅ PDF SAVED SUCCESSFULLY: {OUTPUT_PDF}")

if __name__ == "__main__":
    generate_pdf()
