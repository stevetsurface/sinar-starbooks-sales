"""Reseller pre-order list: forthcoming titles from three sources, merged by ISBN into data/preorder.csv.

1. Team sheet  "Pre-order Sinar Starbooks.xlsx" in Drive (SINAR STARBOOKS / Pre-order): titles the team opens for pre-order,
   with the retail price, publisher minimum, total copies requested by resellers and a status. Its values win.
2. Publisher files: every .xlsx under SINAR STARBOOKS / Email Publihser (new-title lists, Edelweiss order forms),
   kept when the on-sale date falls within the next PUB_WINDOW_DAYS days.
3. Booky Scout picks on the Distribusi side (data/scout_picks.csv, written by the morning sync).

Titles already on the ready-stock list are left out (they ship now). Drive is only readable on Steve's Mac, so this runs
there from scripts/refresh_ready_stock.sh:  python3 scripts/preorder.py
"""
import csv, glob, os, re, sys
from datetime import date, datetime, timedelta

import openpyxl

SSB = os.path.expanduser('~/Library/CloudStorage/GoogleDrive-steve@surfaceskinhabit.com/My Drive/SSB & WBS/SINAR STARBOOKS')
TEAM = os.path.join(SSB, 'Pre-order', 'Pre-order Sinar Starbooks.xlsx')
PUBLISHERS = os.path.join(SSB, 'Email Publihser')
PUB_WINDOW_DAYS = 270      # publisher titles on sale from today up to about nine months out
PREORDER_MIN = 5           # copies requested before a title is ordered, or the publisher minimum if higher
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEADER = ['isbn', 'title', 'author', 'publisher', 'format', 'on_sale', 'price', 'list_price', 'min_qty', 'requested', 'status', 'source', 'as_of']
TEAM_HEADER = ['ISBN', 'Judul', 'Pengarang', 'Penerbit', 'Format', 'Terbit (tanggal)', 'Harga retail (Rp)', 'Minimum penerbit', 'Jumlah diminta', 'Status (Buka / Dipesan / Batal)', 'Catatan']

# publisher column names vary; patterns are tried in order, the first column that matches wins
PUB_COLS = {
    'isbn': [r'^isbn'],
    'title': [r'^title - long$', r'^title$', r'^cover title'],
    'author': [r'^author'],
    'on_sale': [r'on sale date', r'publication date', r'pub date'],
    'list_price': [r'^us price$', r'^price \(usa\)$', r'^published price$'],
    'publisher': [r'^imprint', r'^publisher$', r'^division$'],
    'format': [r'^binding', r'^format code$', r'^format$'],
}
CURRENCY = {r'^us price$': 'US$', r'^price \(usa\)$': 'US$', r'^published price$': '£'}  # "Published Price" is Hachette UK's, in pounds


def isbn(v):
    s = re.sub(r'[^0-9Xx]', '', str(v or ''))
    return s.upper() if len(s) in (10, 13) else ''


def day(v):
    if isinstance(v, datetime): return v.date()
    if isinstance(v, date): return v
    try: return datetime.strptime(str(v).strip()[:10], '%Y-%m-%d').date()
    except ValueError: return None


def num(v):
    try: return float(str(v).replace(',', '')) if v not in (None, '') else None
    except ValueError: return None


def header_row(rows):
    """Index and column map of the first row that names an ISBN column and a title column."""
    for i, r in enumerate(rows[:15]):
        names = [str(c or '').strip().lower() for c in r]
        col, cur = {}, ''
        for key, pats in PUB_COLS.items():
            hit = next(((j, p) for p in pats for j, n in enumerate(names) if re.search(p, n)), (None, None))
            col[key] = hit[0]
            if key == 'list_price' and hit[1]: cur = CURRENCY[hit[1]]
        if col['isbn'] is not None and col['title'] is not None: return i, col, cur
    return None, None, ''


def publisher_titles(today):
    out = {}
    for path in sorted(glob.glob(os.path.join(PUBLISHERS, '**', '*.xlsx'), recursive=True)):
        if os.path.basename(path).startswith('~$'): continue
        try: wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        except Exception as e:
            print('skipped', os.path.basename(path), e, file=sys.stderr); continue
        for ws in wb.worksheets:
            rows = list(ws.iter_rows(values_only=True))
            h, col, cur = header_row(rows)
            if h is None: continue
            get = lambda r, k: r[col[k]] if col[k] is not None and col[k] < len(r) else None
            for r in rows[h + 1:]:
                code, d = isbn(get(r, 'isbn')), day(get(r, 'on_sale'))
                if not code or not d or not (today <= d <= today + timedelta(days=PUB_WINDOW_DAYS)): continue
                out.setdefault(code, {
                    'isbn': code, 'title': str(get(r, 'title') or '').strip(), 'author': str(get(r, 'author') or '').strip().title(),
                    'publisher': str(get(r, 'publisher') or '').strip(), 'format': str(get(r, 'format') or '').strip(),
                    'on_sale': d.isoformat(), 'list_price': (cur + ' ' + format(num(get(r, 'list_price')), 'g')) if num(get(r, 'list_price')) else '', 'source': 'Penerbit',
                })
    return out


def scout_titles():
    p = os.path.join(ROOT, 'data', 'scout_picks.csv')
    if not os.path.exists(p): return {}
    with open(p, encoding='utf-8') as f:
        return {isbn(r['isbn']): {'isbn': isbn(r['isbn']), 'title': r['title'], 'author': r['author'], 'publisher': r['publisher'], 'source': 'Booky Scout'}
                for r in csv.DictReader(f) if r.get('side') == 'Distribusi' and isbn(r.get('isbn'))}


def make_team_sheet():
    """First run: create the team's sheet with its header and a how-to sheet."""
    os.makedirs(os.path.dirname(TEAM), exist_ok=True)
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = 'Pre-order'
    ws.append(TEAM_HEADER); ws.freeze_panes = 'A2'
    for c, w in zip('ABCDEFGHIJK', [16, 40, 24, 22, 12, 16, 18, 16, 15, 28, 40]): ws.column_dimensions[c].width = w
    for c in ws[1]: c.font = openpyxl.styles.Font(bold=True)
    how = wb.create_sheet('Petunjuk')
    for line in [
        'Satu baris per judul yang dibuka untuk pre-order. Dashboard membaca file ini dua kali sehari (10:20 dan 15:20).',
        'Judul dari file penerbit di folder Email Publihser dan dari Booky Scout ikut masuk otomatis. Tulis ISBN-nya di sini untuk mengisi harga, minimum atau jumlah diminta.',
        'Harga retail (Rp): harga jual. Kosong = "harga menyusul" di daftar reseller.',
        'Minimum penerbit: kalau penerbit minta lebih dari 5 eksemplar. Kosong = 5.',
        'Jumlah diminta: total eksemplar dari semua reseller sampai tanggal 20. Tulis totalnya saja, bukan nama reseller.',
        'Status: Buka (default), Dipesan (sudah dipesan ke penerbit), Batal (tidak ditampilkan).',
    ]: how.append([line])
    how.column_dimensions['A'].width = 120
    wb.save(TEAM)
    print('created', TEAM)


def team_titles():
    if not os.path.exists(TEAM): make_team_sheet(); return {}
    ws = openpyxl.load_workbook(TEAM, read_only=True, data_only=True).worksheets[0]
    out = {}
    for r in list(ws.iter_rows(values_only=True))[1:]:
        r = list(r) + [None] * (len(TEAM_HEADER) - len(r))
        code = isbn(r[0])
        if not code: continue
        d = day(r[5])
        out[code] = {k: v for k, v in {
            'isbn': code, 'title': str(r[1] or '').strip(), 'author': str(r[2] or '').strip(), 'publisher': str(r[3] or '').strip(),
            'format': str(r[4] or '').strip(), 'on_sale': d.isoformat() if d else '', 'price': num(r[6]), 'min_qty': num(r[7]),
            'requested': num(r[8]), 'status': str(r[9] or '').strip().capitalize(), 'source': 'Tim',
        }.items() if v not in ('', None)}
    return out


def merge(today):
    with open(os.path.join(ROOT, 'data', 'ready_stock.csv'), encoding='utf-8') as f:
        in_stock = {isbn(r['item_code']) for r in csv.DictReader(f)}
    pub, scout, team = publisher_titles(today), scout_titles(), team_titles()
    out = []
    for code in set(pub) | set(scout) | set(team):
        r = {**pub.get(code, {}), **{k: v for k, v in scout.get(code, {}).items() if k != 'source' or code not in pub}, **team.get(code, {})}
        r['source'] = ' + '.join(s for s, d in (('Tim', team), ('Penerbit', pub), ('Booky Scout', scout)) if code in d)
        if r.get('status') == 'Batal' or not r.get('title'): continue
        if code in in_stock and code not in team: continue
        r['status'] = r.get('status') or 'Buka'
        r['min_qty'] = int(max(PREORDER_MIN, r.get('min_qty') or 0))
        r['requested'] = int(r['requested']) if r.get('requested') is not None else ''
        r['price'] = int(round(r['price'])) if r.get('price') else ''
        r['as_of'] = today.isoformat()
        out.append([r.get(k, '') for k in HEADER])
    # team titles first, then those closest to the minimum, then by on-sale date
    return sorted(out, key=lambda r: ('Tim' not in r[11], -(r[9] or 0) / r[8], r[5] or '9999', r[1]))


if __name__ == '__main__':
    today = date.today()
    rows = merge(today)
    with open(os.path.join(ROOT, 'data', 'preorder.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(HEADER); w.writerows(rows)
    by = {}
    for r in rows: by[r[11]] = by.get(r[11], 0) + 1
    print('wrote preorder.csv', len(rows), 'titles', by)
