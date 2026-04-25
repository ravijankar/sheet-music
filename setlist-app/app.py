#!/usr/bin/env python3
import csv
import gzip
import io
import os
import plistlib
import re
import smtplib
import subprocess
import tempfile
import uuid
import zipfile
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from flask import Flask, render_template_string, request, send_file

app = Flask(__name__)

CSV_PATH = os.path.join(os.path.dirname(__file__), '..', 'set lists', 'MASTER LIST.csv')
CSS_PATH = os.path.join(os.path.dirname(__file__), 'setlist.css')
MDTOPDF = '/opt/homebrew/bin/md-to-pdf'

_EXPORTS = Path(__file__).parent.parent / 'exports'
TENOR_PDF_DIR   = _EXPORTS / 'tenor-pdfs'
BARI_PDF_DIR    = _EXPORTS / 'bari-pdfs'
PLACEHOLDER_DIR = _EXPORTS / 'placeholders'

GMAIL_USER = os.environ.get('GMAIL_USER', 'ravijankar@gmail.com')
GMAIL_APP_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD', 'nona csvs nrvq cspl')
DEFAULT_RECIPIENTS = [
    'mike.sieger@gmail.com',
    'mafiaprincess_75@yahoo.com',
    'joevent@wi.rr.com',
    'vout.oreenie@yahoo.com',
]


def load_master_list():
    charts = {}
    with open(CSV_PATH, newline='', encoding='utf-8-sig') as f:
        for row in csv.reader(f):
            if not row or not row[0].strip():
                continue
            num = row[0].strip()
            title = row[1].strip() if len(row) > 1 else ''
            key = row[2].strip() if len(row) > 2 else ''
            notes = row[3].strip() if len(row) > 3 else ''
            if title and not title.startswith('?'):
                charts[num.lower()] = {
                    'num': num, 'title': title, 'key': key, 'notes': notes
                }
    return charts


def parse_numbers(text):
    """Return list of {'query': str, 'show_num': bool}."""
    items = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('-'):
            query = line[1:].strip()
            if query:
                items.append({'query': query, 'show_num': False})
        else:
            for n in re.split(r'[,\s]+', line):
                n = n.strip()
                if n:
                    items.append({'query': n, 'show_num': True})
    return items


def lookup_chart(query, charts_db):
    """Find chart by number or name (case-insensitive substring)."""
    q = query.strip().lower()
    # Exact number match first, then stripped of leading zeros
    if q in charts_db:
        return charts_db[q]
    stripped = q.lstrip('0') or q
    if stripped in charts_db:
        return charts_db[stripped]
    # Partial name match — return first hit
    for c in charts_db.values():
        if q in c['title'].lower():
            return c
    return None


# ── forScore helpers ──────────────────────────────────────────────────────────

def _fs_pdf_index(pdf_dir):
    """Map normalized chart number -> PDF stem (filename without .pdf)."""
    index = {}
    for pdf in sorted(pdf_dir.glob('*.pdf')):
        m = re.match(r'^(\d+[a-z]?)(?:[\s_]|(?=[A-Z]))', pdf.stem)
        if m:
            key = m.group(1).lstrip('0') or '0'
            if key not in index:
                index[key] = pdf.stem
    return index


def _fs_placeholder_pdf(song_title):
    """Return bytes of a minimal single-page PDF saying '<title> NO CHART'."""
    def esc(s):
        s = s.encode('latin-1', errors='replace').decode('latin-1')
        return s.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')

    font_size = 22 if len(song_title) <= 45 else 16
    stream = (
        f"BT\n/F1 {font_size} Tf\n50 480 Td\n({esc(song_title)}) Tj\n"
        f"0 -60 Td\n/F1 36 Tf\n(NO CHART) Tj\nET\n"
    ).encode('latin-1')

    obj1 = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    obj2 = b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    obj3 = (b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
            b"   /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n")
    obj4 = (f"4 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode()
            + stream + b"\nendstream\nendobj\n")
    obj5 = (b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>\nendobj\n")

    hdr = b"%PDF-1.4\n"
    o = [len(hdr)]
    for obj in (obj1, obj2, obj3, obj4):
        o.append(o[-1] + len(obj))
    xref_pos = o[-1] + len(obj5)
    xref = (
        f"xref\n0 6\n0000000000 65535 f \n"
        + "".join(f"{x:010d} 00000 n \n" for x in o)
        + f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    return hdr + obj1 + obj2 + obj3 + obj4 + obj5 + xref


def _fs_get_placeholder(song_title):
    """Return (score_title, pdf_bytes) for a NO CHART placeholder."""
    score_title = f"{song_title} - NO CHART"
    path = PLACEHOLDER_DIR / f"{score_title}.pdf"
    if path.exists():
        pdf_bytes = path.read_bytes()
    else:
        pdf_bytes = _fs_placeholder_pdf(song_title)
        PLACEHOLDER_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pdf_bytes)
    return score_title, pdf_bytes


_UID = plistlib.UID
_NKA_DICT_CLASS  = {'$classname': 'NSMutableDictionary', '$classes': ['NSMutableDictionary', 'NSDictionary', 'NSObject']}
_NKA_ARRAY_CLASS = {'$classname': 'NSMutableArray',      '$classes': ['NSMutableArray', 'NSArray', 'NSObject']}


def _make_nka_setlist(set_entries):
    """
    Build a gzip-compressed NSKeyedArchiver binary plist (.4ss) for forScore.

    set_entries: list of (set_label, [(title_stem, filepath), ...])
    Set separators (Set 2, 3, …) are inserted automatically between sets.
    Returns bytes.
    """
    # Fixed object layout:
    #  [0] $null  [1] NSMutableArray  [2] 'Title'  [3] 'Identifier'
    #  [4] 'FilePath'  [5] 'Placeholder'  [6] dict class  [7] array class
    #  [8+] song/separator dicts and their string values
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
            # Set separator entry
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


def _forscore_set_entries(sets, part):
    """
    Build set_entries and a pdf_sources dict for the given part.
    Returns (set_entries, pdf_sources) where:
      set_entries: list of (set_label, [(title, filepath), ...])
      pdf_sources: dict of filepath -> Path on disk (None for placeholders already saved)
    Placeholder PDFs are written to PLACEHOLDER_DIR as a side effect.
    """
    charts_db = load_master_list()
    pdf_dir   = TENOR_PDF_DIR if part == 'tenor' else BARI_PDF_DIR
    pdf_index = _fs_pdf_index(pdf_dir)

    set_entries = []
    pdf_sources = {}   # filepath (with .pdf) -> Path on disk

    for set_num, items in sets:
        songs = []
        for item in items:
            if item['show_num']:
                c = lookup_chart(item['query'], charts_db)
                num = c['num'] if c else None
                song_title = c['title'] if c else item['query']
            else:
                num = None
                song_title = item['query']

            key = (num.lstrip('0') or '0') if num else None

            if key and key in pdf_index:
                stem = pdf_index[key]
                filepath = stem + '.pdf'
                songs.append((stem, filepath))
                pdf_sources[filepath] = pdf_dir / filepath
            else:
                score_title, _ = _fs_get_placeholder(song_title)
                filepath = score_title + '.pdf'
                songs.append((score_title, filepath))
                pdf_sources[filepath] = PLACEHOLDER_DIR / filepath

        set_entries.append((f'SET {set_num}', songs))

    return set_entries, pdf_sources


def build_forscore_4ss(date, venue, sets, part):
    """Return BytesIO of a .4ss file (setlist only) for `part`."""
    set_entries, _ = _forscore_set_entries(sets, part)
    return io.BytesIO(_make_nka_setlist(set_entries))


def build_forscore_4sc(date, venue, sets, part):
    """Return BytesIO of a ZIP containing the .4ss + chart PDFs for `part`."""
    part_label = 'Tenor' if part == 'tenor' else 'Bari'
    set_entries, pdf_sources = _forscore_set_entries(sets, part)
    base = f"{date} {venue}"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{base} - {part_label}.4ss", _make_nka_setlist(set_entries))
        for filepath, src_path in pdf_sources.items():
            if src_path.exists():
                zf.write(src_path, filepath)
    buf.seek(0)
    return buf


# ── PDF / email helpers ────────────────────────────────────────────────────────

FRONTMATTER = f"""\
---
pdf_options:
  format: Letter
  margin: 8mm 10mm
stylesheet: {CSS_PATH}
---
"""


def build_markdown(date, venue, sets):
    charts_db = load_master_list()
    try:
        date_display = datetime.strptime(date, '%Y-%m-%d').strftime('%m/%d/%Y')
    except ValueError:
        date_display = date
    title = f"{date_display} {venue}"
    if len(sets) == 1:
        title += f" — Set {sets[0][0]}"
    active_sets = [(n, it) for n, it in sets if it]
    lines = [FRONTMATTER]
    for idx, (set_num, items) in enumerate(active_sets):
        if idx > 0:
            lines += ['', '<div style="break-before: page; page-break-before: always;"></div>', '']
        section_title = f"{title} — Set {set_num}" if len(active_sets) > 1 else title
        lines += [f"# {section_title}"]
        lines += ['| # | Title | Key | Solos / Notes |',
                  '|---|-------|-----|---------------|']
        for item in items:
            if not item['show_num']:
                lines.append(f"|  | {item['query']} |  |  |")
                continue
            c = lookup_chart(item['query'], charts_db)
            if c:
                lines.append(f"| {c['num']} | {c['title']} | {c['key']} | {c['notes']} |")
            else:
                lines.append(f"| {item['query']} | ??? | | |")
        lines.append('')
    return '\n'.join(lines)


def generate_pdf(markdown_text):
    with tempfile.NamedTemporaryFile(suffix='.md', mode='w', delete=False,
                                     encoding='utf-8', dir='/tmp') as f:
        f.write(markdown_text)
        md_path = f.name
    pdf_path = md_path[:-3] + '.pdf'
    try:
        result = subprocess.run(
            [MDTOPDF, md_path],
            capture_output=True, text=True
        )
        if not os.path.exists(pdf_path):
            raise RuntimeError(f"md-to-pdf failed:\n{result.stderr}")
        with open(pdf_path, 'rb') as f:
            return f.read()
    finally:
        for p in (md_path, pdf_path):
            if os.path.exists(p):
                os.unlink(p)


def send_email(pdf_bytes, filename, to_addrs, comment=''):
    msg = MIMEMultipart()
    msg['From'] = GMAIL_USER
    msg['To'] = ', '.join(to_addrs)
    msg['Subject'] = filename.replace('.pdf', '')
    body = (comment + '\n\n' if comment else '') + 'Set list attached.'
    msg.attach(MIMEText(body, 'plain'))
    attachment = MIMEApplication(pdf_bytes, _subtype='pdf')
    attachment.add_header('Content-Disposition', 'attachment', filename=filename)
    msg.attach(attachment)
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        smtp.sendmail(GMAIL_USER, to_addrs, msg.as_string())


TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Set List Builder</title>
<style>
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, sans-serif;
    max-width: 640px;
    margin: 40px auto;
    padding: 0 24px;
    color: #111;
  }
  h1 { font-size: 1.4em; margin-bottom: 4px; }
  p.sub { color: #555; margin-top: 0; font-size: 0.9em; }
  label { display: block; margin-top: 18px; font-weight: 600; font-size: 0.9em; }
  input[type=text], input[type=date] {
    width: 100%; padding: 7px 9px; border: 1px solid #ccc;
    border-radius: 4px; font-size: 1em; margin-top: 4px;
  }
  textarea {
    width: 100%; padding: 7px 9px; border: 1px solid #ccc;
    border-radius: 4px; font-family: monospace; font-size: 0.95em;
    margin-top: 4px; resize: vertical;
  }
  .set-block {
    margin-top: 24px; border-top: 1px solid #ddd; padding-top: 16px;
  }
  .set-block h2 { font-size: 1em; margin: 0 0 4px 0; }
  .buttons { margin-top: 24px; display: flex; gap: 12px; }
  button {
    padding: 10px 28px;
    border: none; border-radius: 4px;
    cursor: pointer; font-size: 1em;
  }
  button[type=submit] { background: #111; color: #fff; }
  button[type=submit]:hover { background: #333; }
  button[type=button] { background: #eee; color: #333; }
  button[type=button]:hover { background: #ddd; }
  .error { color: #c00; margin-top: 14px; font-size: 0.9em; }
  .success { color: #060; margin-top: 14px; font-size: 0.9em; }
</style>
</head>
<body>
<h1>Set List Builder</h1>
<p class="sub">Enter chart numbers one per line or space-separated on one line. For a title with no chart, enter it on its own line starting with a dash: <code>- Devil With a Blue Dress</code></p>
<form method="post" action="/generate">
  <label>Date</label>
  <input type="date" name="date" id="date" required value="{{ date }}">

  <label>Venue</label>
  <input type="text" name="venue" id="venue" placeholder="e.g. Salty Toad" required value="{{ venue }}">

  <div class="set-block">
    <h2>Set 1</h2>
    <label>Chart numbers</label>
    <textarea name="set1" id="set1" rows="14" placeholder="1&#10;17&#10;85&#10;88&#10;92">{{ set1 }}</textarea>
  </div>

  <div class="set-block">
    <h2>Set 2 <span style="font-weight:normal;color:#888">(optional)</span></h2>
    <label>Chart numbers</label>
    <textarea name="set2" id="set2" rows="14" placeholder="23&#10;10&#10;76">{{ set2 }}</textarea>
  </div>

  <div class="set-block">
    <h2>Set 3 <span style="font-weight:normal;color:#888">(optional)</span></h2>
    <label>Chart numbers</label>
    <textarea name="set3" id="set3" rows="10">{{ set3 }}</textarea>
  </div>

  <label>Email to <span style="font-weight:normal;color:#888">(one per line)</span></label>
  <textarea name="email_to" id="email_to" rows="5" style="font-size:0.85em;">{{ email_to }}</textarea>

  <label>Comment <span style="font-weight:normal;color:#888">(optional)</span></label>
  <textarea name="email_comment" id="email_comment" rows="3" placeholder="e.g. See you Thursday!">{{ email_comment }}</textarea>

  <div class="buttons">
    <button type="submit">Generate PDF</button>
    <button type="submit" formaction="/email" style="background:#1a73e8;color:#fff;">Email PDF</button>
    <button type="submit" formaction="/forscore/tenor/4ss" style="background:#1e7e34;color:#fff;">Tenor .4ss</button>
    <button type="submit" formaction="/forscore/tenor/4sc" style="background:#1e7e34;color:#fff;">Tenor+Charts</button>
    <button type="submit" formaction="/forscore/bari/4ss" style="background:#1e7e34;color:#fff;">Bari .4ss</button>
    <button type="submit" formaction="/forscore/bari/4sc" style="background:#1e7e34;color:#fff;">Bari+Charts</button>
    <button type="button" onclick="clearAll()">Clear</button>
  </div>
</form>
{% if error %}
<p class="error">{{ error }}</p>
{% endif %}
{% if success %}
<p class="success">{{ success }}</p>
{% endif %}
<script>
const FIELDS = ['date', 'venue', 'set1', 'set2', 'set3', 'email_to', 'email_comment'];

function save() {
  FIELDS.forEach(id => {
    const el = document.getElementById(id);
    if (el) localStorage.setItem('sl_' + id, el.value);
  });
}

function restore() {
  FIELDS.forEach(id => {
    const el = document.getElementById(id);
    const val = localStorage.getItem('sl_' + id);
    if (el && val) el.value = val;
  });
}

function clearAll() {
  FIELDS.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
    localStorage.removeItem('sl_' + id);
  });
}

FIELDS.forEach(id => {
  const el = document.getElementById(id);
  if (el) el.addEventListener('input', save);
});

restore();
</script>
</body>
</html>
"""


@app.route('/', methods=['GET'])
def index():
    return render_template_string(
        TEMPLATE, date='', venue='', set1='', set2='', set3='',
        email_to='\n'.join(DEFAULT_RECIPIENTS), email_comment='', error='', success=''
    )


def _parse_form():
    return {
        'date': request.form.get('date', '').strip(),
        'venue': request.form.get('venue', '').strip(),
        'set1': request.form.get('set1', '').strip(),
        'set2': request.form.get('set2', '').strip(),
        'set3': request.form.get('set3', '').strip(),
        'email_to': request.form.get('email_to', '').strip(),
        'email_comment': request.form.get('email_comment', '').strip(),
    }


def _build_sets(f):
    sets = []
    if f['set1']:
        sets.append((1, parse_numbers(f['set1'])))
    if f['set2']:
        sets.append((2, parse_numbers(f['set2'])))
    if f['set3']:
        sets.append((3, parse_numbers(f['set3'])))
    return sets


def _error(f, msg):
    return render_template_string(
        TEMPLATE, date=f['date'], venue=f['venue'],
        set1=f['set1'], set2=f['set2'], set3=f['set3'],
        email_to=f['email_to'], email_comment=f['email_comment'],
        error=msg, success=''
    )


def _success(f, msg):
    return render_template_string(
        TEMPLATE, date=f['date'], venue=f['venue'],
        set1=f['set1'], set2=f['set2'], set3=f['set3'],
        email_to=f['email_to'], email_comment=f['email_comment'],
        error='', success=msg
    )


@app.route('/generate', methods=['POST'])
def generate():
    f = _parse_form()
    sets = _build_sets(f)
    if not sets:
        return _error(f, 'Enter at least one chart number.')
    try:
        md = build_markdown(f['date'], f['venue'], sets)
        pdf_bytes = generate_pdf(md)
    except Exception as e:
        return _error(f, str(e))
    filename = f"{f['date']} {f['venue']}.pdf"
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename
    )


@app.route('/email', methods=['POST'])
def email_pdf():
    f = _parse_form()
    sets = _build_sets(f)
    if not sets:
        return _error(f, 'Enter at least one chart number.')
    raw = f['email_to']
    to_addrs = [a.strip() for a in raw.splitlines() if a.strip()]
    if not to_addrs:
        to_addrs = [GMAIL_USER]
    try:
        md = build_markdown(f['date'], f['venue'], sets)
        pdf_bytes = generate_pdf(md)
        filename = f"{f['date']} {f['venue']}.pdf"
        send_email(pdf_bytes, filename, to_addrs, comment=f['email_comment'])
    except Exception as e:
        return _error(f, str(e))
    return _success(f, f"Sent to {', '.join(to_addrs)}.")


@app.route('/forscore/<part>/<fmt>', methods=['POST'])
def forscore(part, fmt):
    if part not in ('tenor', 'bari') or fmt not in ('4ss', '4sc'):
        return ('Not found', 404)
    f = _parse_form()
    sets = _build_sets(f)
    if not sets:
        return _error(f, 'Enter at least one chart number.')
    part_label = 'Tenor' if part == 'tenor' else 'Bari'
    base = f"{f['date']} {f['venue']} - {part_label}"
    try:
        if fmt == '4ss':
            buf = build_forscore_4ss(f['date'], f['venue'], sets, part)
            return send_file(buf, mimetype='application/octet-stream',
                             as_attachment=True, download_name=f"{base}.4ss")
        else:
            buf = build_forscore_4sc(f['date'], f['venue'], sets, part)
            return send_file(buf, mimetype='application/zip',
                             as_attachment=True, download_name=f"{base}.zip")
    except Exception as e:
        return _error(f, str(e))


if __name__ == '__main__':
    app.run(debug=True, port=5001)
