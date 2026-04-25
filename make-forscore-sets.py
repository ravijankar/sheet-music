#!/usr/bin/env python3
"""
Generate forScore setlist (.4ss) files from a Markdown set list.

Usage:
    python make-forscore-sets.py [setlist.md]

Default: most recent .md file in set-lists/ (excluding _template.md).

Output:
    exports/<name> - Tenor.4ss
    exports/<name> - Bari.4ss
    exports/placeholders/*.pdf  (one per missing chart, import these into forScore)
"""

import gzip
import io
import plistlib
import re
import sys
import uuid
import zipfile
from pathlib import Path

SHEET_DIR = Path(__file__).parent
TENOR_DIR = SHEET_DIR / "exports" / "tenor-pdfs"
BARI_DIR  = SHEET_DIR / "exports" / "bari-pdfs"
SETLISTS_DIR = SHEET_DIR / "set-lists"
PLACEHOLDER_DIR = SHEET_DIR / "exports" / "placeholders"
OUT_DIR  = SHEET_DIR / "exports"


# ── PDF index ─────────────────────────────────────────────────────────────────

def build_pdf_index(pdf_dir):
    """Map normalized chart number -> PDF stem (filename without .pdf)."""
    index = {}
    for pdf in sorted(pdf_dir.glob("*.pdf")):
        stem = pdf.stem
        m = re.match(r'^(\d+[a-z]?)(?:[\s_]|(?=[A-Z]))', stem)
        if not m:
            continue
        num = m.group(1).lstrip('0') or '0'
        if num not in index:  # first sorted match wins (e.g. chart 76 vs 76-in-G)
            index[num] = stem
    return index


# ── Set list parser ────────────────────────────────────────────────────────────

def parse_setlist(md_path):
    """Return (title, sets) where sets = list of (set_label, [(num_or_None, song_title), ...])."""
    title = Path(md_path).stem
    sets = []
    current_set_label = 'SET 1'
    current_entries = []
    with open(md_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            m = re.match(r'^##\s+(.+)', line)
            if m:
                if current_entries:
                    sets.append((current_set_label, current_entries))
                    current_entries = []
                current_set_label = m.group(1).strip().upper()
                continue
            if not line.startswith('|'):
                continue
            parts = line.split('|')
            if len(parts) < 4:
                continue
            num_cell   = parts[1].strip()
            title_cell = parts[2].strip()
            if num_cell == '#' or re.match(r'^-+:?$', num_cell):
                continue
            if not title_cell or re.match(r'^-+', title_cell):
                continue
            num = num_cell if re.match(r'^\d+[a-z]?$', num_cell) else None
            current_entries.append((num, title_cell))
    if current_entries:
        sets.append((current_set_label, current_entries))
    return title, sets


# ── Placeholder PDF generator ──────────────────────────────────────────────────

def _pdf_str(s):
    """Escape a string for use in a PDF literal string (latin-1 only)."""
    s = s.encode('latin-1', errors='replace').decode('latin-1')
    return s.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')

def make_placeholder_pdf(song_title):
    """Return bytes of a minimal valid single-page PDF saying '<title>: NO CHART'."""
    title_font = 22 if len(song_title) <= 45 else 16
    safe_title = _pdf_str(song_title)

    stream = (
        f"BT\n"
        f"/F1 {title_font} Tf\n"
        f"50 480 Td\n"
        f"({safe_title}) Tj\n"
        f"0 -60 Td\n"
        f"/F1 36 Tf\n"
        f"(NO CHART) Tj\n"
        f"ET\n"
    ).encode('latin-1')

    obj1 = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    obj2 = b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    obj3 = (
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"   /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\n"
        b"endobj\n"
    )
    obj4 = (
        f"4 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode() +
        stream + b"\nendstream\nendobj\n"
    )
    obj5 = (
        b"5 0 obj\n"
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>\n"
        b"endobj\n"
    )

    header = b"%PDF-1.4\n"
    o1 = len(header)
    o2 = o1 + len(obj1)
    o3 = o2 + len(obj2)
    o4 = o3 + len(obj3)
    o5 = o4 + len(obj4)
    xref_pos = o5 + len(obj5)

    xref = (
        f"xref\n0 6\n"
        f"0000000000 65535 f \n"
        f"{o1:010d} 00000 n \n"
        f"{o2:010d} 00000 n \n"
        f"{o3:010d} 00000 n \n"
        f"{o4:010d} 00000 n \n"
        f"{o5:010d} 00000 n \n"
        f"trailer\n<< /Size 6 /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode()

    return header + obj1 + obj2 + obj3 + obj4 + obj5 + xref


def get_or_create_placeholder(song_title):
    """Return the forScore score title for a missing chart, creating the PDF if needed."""
    # Score title = filename stem: "Devil With a Blue Dress - NO CHART"
    score_title = f"{song_title} - NO CHART"
    pdf_path = PLACEHOLDER_DIR / f"{score_title}.pdf"
    if not pdf_path.exists():
        PLACEHOLDER_DIR.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(make_placeholder_pdf(song_title))
        print(f"  Created placeholder: {pdf_path.name}")
    return score_title


# ── forScore .4ss writer ───────────────────────────────────────────────────────

_UID = plistlib.UID
_NKA_DICT_CLASS  = {'$classname': 'NSMutableDictionary', '$classes': ['NSMutableDictionary', 'NSDictionary', 'NSObject']}
_NKA_ARRAY_CLASS = {'$classname': 'NSMutableArray',      '$classes': ['NSMutableArray', 'NSArray', 'NSObject']}


def make_4ss_bytes(set_entries):
    """
    Build gzip-compressed NSKeyedArchiver binary plist bytes for a forScore setlist.
    set_entries: list of (set_label, [(title_stem, filepath), ...])
    """
    KEY_TITLE       = _UID(2)
    KEY_ID          = _UID(3)
    KEY_FP          = _UID(4)
    KEY_PLACEHOLDER = _UID(5)
    CLASS_DICT      = _UID(6)
    CLASS_ARRAY     = _UID(7)

    objects = [
        '$null', None,
        'Title', 'Identifier', 'FilePath', 'Placeholder',
        _NKA_DICT_CLASS, _NKA_ARRAY_CLASS,
    ]
    item_uids = []

    for set_idx, (set_label, songs) in enumerate(set_entries):
        if set_idx > 0:
            si = len(objects)
            id1, id2 = str(uuid.uuid4()).upper(), str(uuid.uuid4()).upper()
            objects += [
                {'NS.keys': [KEY_ID, KEY_FP, KEY_TITLE, KEY_PLACEHOLDER],
                 'NS.objects': [_UID(si+1), _UID(si+2), _UID(si+3), _UID(si+4)],
                 '$class': CLASS_DICT},
                id1, id2, set_label, 1,
            ]
            item_uids.append(_UID(si))

        for title, filepath in songs:
            si = len(objects)
            objects += [
                {'NS.keys': [KEY_TITLE, KEY_ID, KEY_FP],
                 'NS.objects': [_UID(si+1), _UID(si+2), _UID(si+3)],
                 '$class': CLASS_DICT},
                title, str(uuid.uuid4()).upper(), filepath,
            ]
            item_uids.append(_UID(si))

    objects[1] = {'NS.objects': item_uids, '$class': CLASS_ARRAY}
    top = {
        '$version': 100000,
        '$archiver': 'NSKeyedArchiver',
        '$top': {'setlist': _UID(1)},
        '$objects': objects,
    }
    plist_bytes = plistlib.dumps(top, fmt=plistlib.FMT_BINARY)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode='wb', mtime=0) as gz:
        gz.write(plist_bytes)
    return buf.getvalue()


def write_4ss(out_path, set_entries):
    data = make_4ss_bytes(set_entries)
    out_path.write_bytes(data)
    total = sum(len(songs) for _, songs in set_entries)
    real  = sum(1 for _, songs in set_entries for _, fp in songs if 'NO CHART' not in fp)
    print(f"  Written: {out_path.name} ({real} charts, {total - real} placeholders)")


def write_4sc(out_path, set_entries, pdf_dir):
    """Write a .4sc ZIP containing the .4ss setlist + all chart PDFs."""
    ss_name = out_path.stem + '.4ss'
    total = real = 0
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(ss_name, make_4ss_bytes(set_entries))
        for _, songs in set_entries:
            for _, filepath in songs:
                total += 1
                if 'NO CHART' in filepath:
                    src = PLACEHOLDER_DIR / filepath
                else:
                    src = pdf_dir / filepath
                if src.exists():
                    zf.write(src, filepath)
                    real += 1
    print(f"  Written: {out_path.name} ({real} of {total} PDFs included)")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) > 1:
        md_path = Path(sys.argv[1])
    else:
        candidates = sorted(p for p in SETLISTS_DIR.glob("*.md")
                            if not p.name.startswith('_'))
        if not candidates:
            sys.exit("No .md files found in set-lists/")
        md_path = candidates[-1]

    print(f"Set list: {md_path.name}")

    setlist_title, sets = parse_setlist(md_path)
    total = sum(len(entries) for _, entries in sets)
    print(f"Entries: {total} total across {len(sets)} set(s)")

    tenor_index = build_pdf_index(TENOR_DIR)
    bari_index  = build_pdf_index(BARI_DIR)

    tenor_set_entries = []
    bari_set_entries  = []

    for set_label, entries in sets:
        tenor_songs, bari_songs = [], []
        for num, song_title in entries:
            key = (num.lstrip('0') or '0') if num else None

            if key and key in tenor_index:
                stem = tenor_index[key]
                tenor_songs.append((stem, stem + '.pdf'))
            else:
                score_title = get_or_create_placeholder(song_title)
                tenor_songs.append((score_title, score_title + '.pdf'))

            if key and key in bari_index:
                stem = bari_index[key]
                bari_songs.append((stem, stem + '.pdf'))
            else:
                score_title = get_or_create_placeholder(song_title)
                bari_songs.append((score_title, score_title + '.pdf'))

        tenor_set_entries.append((set_label, tenor_songs))
        bari_set_entries.append((set_label, bari_songs))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_4ss(OUT_DIR / f"{setlist_title} - Tenor.4ss", tenor_set_entries)
    write_4ss(OUT_DIR / f"{setlist_title} - Bari.4ss",  bari_set_entries)
    write_4sc(OUT_DIR / f"{setlist_title} - Tenor.zip", tenor_set_entries, TENOR_DIR)
    write_4sc(OUT_DIR / f"{setlist_title} - Bari.zip",  bari_set_entries,  BARI_DIR)


if __name__ == '__main__':
    main()
