#!/usr/bin/env python3
"""
LEGAL DOCUMENT PDF COMPILER — Fortress Prime
==============================================
Converts all .txt legal documents in the Prime Trust NAS folder
into court-ready PDFs with proper pagination and legal typography.
Skips email drafts (files containing 'EMAIL' in the name).
"""

import os
import sys
from pathlib import Path

from fpdf import FPDF

NAS_CASE_DIR = "/mnt/fortress_nas/sectors/legal/prime-trust-23-11161"
SKIP_KEYWORDS = ["EMAIL"]

LINE_H = 5.5
FONT_SIZE = 11

UNICODE_MAP = {
    "\u2014": "--",
    "\u2013": "-",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
    "\u00a7": "S.",
    "\u00b6": "P.",
    "\u2022": "*",
    "\u200e": "",
    "\u200f": "",
    "\u00ad": "-",
}


def _latin1_safe(text: str) -> str:
    for uc, repl in UNICODE_MAP.items():
        text = text.replace(uc, repl)
    return text.encode("latin-1", errors="replace").decode("latin-1")


class LegalDoc(FPDF):
    def header(self):
        if self.page_no() > 1:
            self.set_font("Times", "I", 8)
            self.cell(
                0, 8,
                "IN RE: PRIME CORE TECHNOLOGIES d/b/a PRIME TRUST -- Case No. 23-11161-JKS",
                align="R",
            )
            self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font("Times", "I", 8)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")


PAGE_BREAK_MARKERS = ("DOCUMENT ", "CHECKLIST")


def _is_separator(line: str) -> bool:
    stripped = line.strip()
    if len(stripped) < 10:
        return False
    return all(c in ("=", "-", "_", "*") for c in stripped)


def _is_page_break(line: str) -> bool:
    stripped = line.strip()
    return any(stripped.startswith(m) for m in PAGE_BREAK_MARKERS)


def should_skip(filename: str) -> bool:
    upper = filename.upper()
    return any(kw in upper for kw in SKIP_KEYWORDS)


def convert_file(txt_path: Path):
    pdf = LegalDoc("P", "mm", "Letter")
    pdf.alias_nb_pages()
    pdf.set_left_margin(25)
    pdf.set_right_margin(25)
    pdf.set_auto_page_break(auto=True, margin=25)
    pdf.add_page()
    pdf.set_font("Times", "", FONT_SIZE)

    usable_w = pdf.w - pdf.l_margin - pdf.r_margin

    with open(txt_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    for line in lines:
        raw = line.rstrip("\n\r")
        safe = _latin1_safe(raw.expandtabs(4))

        if not safe.strip():
            pdf.ln(LINE_H)
            continue

        if _is_separator(safe):
            y = pdf.get_y()
            pdf.line(pdf.l_margin, y + 2, pdf.l_margin + usable_w, y + 2)
            pdf.ln(LINE_H)
            continue

        if _is_page_break(safe):
            pdf.add_page()

        leading_spaces = len(safe) - len(safe.lstrip(" "))
        indent = min(leading_spaces * 1.8, 40)
        content = safe.lstrip(" ")

        text_w = usable_w - indent

        is_bold = content.startswith(("DOCUMENT ", "BACKGROUND", "URGENCY",
                                       "IMMEDIATE REQUEST", "CONTENTS:",
                                       "MAIL TO:", "METHOD:", "STATUS:",
                                       "FORENSIC EVIDENCE", "EXECUTIVE SUMMARY",
                                       "SEARCH PARAMETERS", "RESULTS",
                                       "APPENDIX", "DETAILED FINDINGS",
                                       "LEGAL SIGNIFICANCE", "FORTRESS PRIME",
                                       "CERTIFIED MAIL", "Package Generated:",
                                       "Case:", "CRITICAL DATE:",
                                       "Re:", "Dear ", "Respectfully,",
                                       "VIA EMAIL"))

        if is_bold:
            pdf.set_font("Times", "B", FONT_SIZE)
        else:
            pdf.set_font("Times", "", FONT_SIZE)

        str_w = pdf.get_string_width(content)

        if str_w <= text_w:
            pdf.set_x(pdf.l_margin + indent)
            pdf.cell(text_w, LINE_H, content, new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.set_x(pdf.l_margin + indent)
            pdf.multi_cell(text_w, LINE_H, content, align="L")

        if is_bold:
            pdf.set_font("Times", "", FONT_SIZE)

    pdf_path = txt_path.with_suffix(".pdf")
    pdf.output(str(pdf_path))
    return pdf_path


def main():
    print("[*] Legal Document PDF Compiler -- Prime Trust 23-11161-JKS")
    print(f"    Source: {NAS_CASE_DIR}")
    print()

    compiled = 0
    skipped = 0

    for root, dirs, files in os.walk(NAS_CASE_DIR):
        for fname in sorted(files):
            if not fname.endswith(".txt"):
                continue

            txt_path = Path(root) / fname
            rel = txt_path.relative_to(NAS_CASE_DIR)

            if should_skip(fname):
                print(f"  [-] SKIP (email draft): {rel}")
                skipped += 1
                continue

            try:
                pdf_path = convert_file(txt_path)
                pdf_rel = pdf_path.relative_to(NAS_CASE_DIR)
                size_kb = pdf_path.stat().st_size / 1024
                print(f"  [+] COMPILED: {rel} -> {pdf_rel} ({size_kb:.1f} KB)")
                compiled += 1
            except Exception as e:
                print(f"  [!] FAILED: {rel} -- {e}")

    print()
    print(f"[*] Done. {compiled} PDFs compiled, {skipped} email drafts skipped.")
    print(f"    Output location: {NAS_CASE_DIR}/")


if __name__ == "__main__":
    main()
