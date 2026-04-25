#!/usr/bin/env python3
import pdfplumber
import os
import re
import sys

SRC = "/Users/john/Music/sheet-music/set lists"
DST = "/Users/john/Music/sheet-music/set-lists"

def table_to_md(rows):
    lines = ["| # | Title | Key | Solos / Notes |",
             "|---|-------|-----|---------------|"]
    for row in rows:
        num, title, key, notes = (row + ['', '', '', ''])[:4]
        title = (title or '').replace('\n', ' ')
        notes = (notes or '').replace('\n', ' ')
        lines.append(f"| {num or ''} | {title} | {key or ''} | {notes} |")
    return '\n'.join(lines)

def convert(pdf_path, md_path):
    basename = os.path.splitext(os.path.basename(pdf_path))[0]
    # Extract date and venue from filename: "YYYY-MM-DD Venue Name"
    m = re.match(r'(\d{4}-\d{2}-\d{2})\s+(.*)', basename)
    date = m.group(1) if m else basename
    venue = m.group(2) if m else ''

    with pdfplumber.open(pdf_path) as pdf:
        sets = []
        for page in pdf.pages:
            # Try to get heading text (above the table)
            table = page.extract_table()
            text = page.extract_text() or ''
            # Grab first line as set label if it mentions "set"
            first_line = text.split('\n')[0] if text else ''
            set_label = ''
            sm = re.search(r'set\s*(\d+)', first_line, re.IGNORECASE)
            if sm:
                set_label = f"Set {sm.group(1)}"
            else:
                set_label = f"Set {len(sets) + 1}"

            if table:
                sets.append((set_label, table))

    if not sets:
        print(f"  skipped (no tables): {basename}")
        return

    lines = [f"# {date} {venue}", '']
    for label, rows in sets:
        lines += [f"## {label}", '', table_to_md(rows), '']

    with open(md_path, 'w') as f:
        f.write('\n'.join(lines))
    print(f"  ✓ {basename}")

os.makedirs(DST, exist_ok=True)
pdfs = sorted(f for f in os.listdir(SRC) if f.endswith('.pdf')
              and re.match(r'\d{4}-\d{2}-\d{2}', f))

print(f"Converting {len(pdfs)} set lists...")
for pdf_file in pdfs:
    md_file = os.path.splitext(pdf_file)[0] + '.md'
    convert(os.path.join(SRC, pdf_file), os.path.join(DST, md_file))

print(f"\nDone. {len(pdfs)} files written to set-lists/")
