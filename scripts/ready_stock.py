"""Reseller ready-stock list from Sinar's Accurate warehouse snapshot ("Acc dd.mm.yyyy.xlsx", Quantity Item by Warehouse).

The snapshot lives in Drive (SSB & WBS / SINAR STARBOOKS / Daily Stock Warehouse), which the GitHub sync cannot read,
so this runs on Steve's Mac:  python3 scripts/ready_stock.py [path-to-Acc.xlsx]
With no path it takes the newest snapshot in the synced Drive folder. Writes data/ready_stock.csv.
"""
import csv, glob, os, re, sys
from datetime import datetime

import openpyxl

DRIVE = os.path.expanduser('~/Library/CloudStorage/GoogleDrive-steve@surfaceskinhabit.com/My Drive/SSB & WBS/SINAR STARBOOKS/Daily Stock Warehouse')
READY_MIN_QTY = 3          # copies on offer before a title goes on the list
STORE_KEEP = 2             # copies each Wonder store keeps on its shelf; the rest is offered
NOT_FOR_RESELLERS = re.compile(r'VOUCHER|PAPER ?BAG|KARDUS|PACKING|GIFT ?WRAP|BUKU PROMO')  # vouchers, bags, packing, gift wrap and promo bundles carry stock but are not merchandise
NOT_OURS = re.compile(r'GRAMEDIA')  # Gramedia-published titles are bought locally for our stores, not distributed by us
FAR_STORES = re.compile(r'BALI')  # Bali stores can't get stock to Jakarta resellers in time (reseller meeting, 3 Nov)
HEADER = ['item_code', 'item_name', 'group', 'category', 'supplier', 'price', 'offer_qty', 'centre', 'stores_offer', 'offer_by_location', 'as_of']

KIDS = re.compile(r'TODDLER|BABY|CHILDREN|EARLY READER|MIDDLE GRADE')
COMICS = re.compile(r'GRAPHIC NOVEL|MANGA|COMIC')
GIFT = re.compile(r'STATIONERY|PROMO|TOY|GIFT')


def group(cat):
    """The dashboard's four reseller categories, from Accurate's finer item category."""
    if GIFT.search(cat): return 'Alat tulis & gift'
    if COMICS.search(cat): return 'Komik & manga'
    if KIDS.search(cat): return 'Buku anak'
    return 'Buku umum'


def newest():
    def day(p):
        m = re.search(r'Acc (\d{2})\.(\d{2})\.(\d{4})', os.path.basename(p))
        return datetime(int(m[3]), int(m[2]), int(m[1])) if m else datetime.min
    files = [p for p in glob.glob(os.path.join(DRIVE, 'Acc *.xlsx')) if day(p) > datetime.min]
    if not files: sys.exit('no Acc snapshot in ' + DRIVE)
    return max(files, key=day)


def ready(path):
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
    it = ws.iter_rows(values_only=True)
    as_of = ''
    for r in it:
        cells = [c for c in r if c is not None]
        if cells and str(cells[0]).startswith('As of'):
            d = str(cells[0])[6:].strip()  # "30 October 2026" or "12 Mar 2026"
            as_of = datetime.strptime(d, '%d %B %Y' if len(d.split()[1]) > 3 else '%d %b %Y').date().isoformat()
        if 'Item No.' in r:
            col = {str(h).strip(): i for i, h in enumerate(r) if h is not None}
            break
    stores = [(h[len('WONDER '):], i) for h, i in col.items() if h.startswith('WONDER ') and not FAR_STORES.search(h)]
    n = lambda v: max(0, int(v)) if isinstance(v, (int, float)) else 0
    out = []
    for r in it:
        code, name = r[col['Item No.']], r[col['Item Description']]
        if code is None or not name: continue
        name, sup = str(name).strip(), str(r[col['Preferred Vendor Name']] or '').strip()
        price = n(r[col['Unit Price']])
        if not price or NOT_FOR_RESELLERS.search(name.upper()) or NOT_OURS.search(sup.upper()): continue
        centre = n(r[col['CENTRE']])
        offer = [(s, n(r[i]) - STORE_KEEP) for s, i in stores if n(r[i]) > STORE_KEEP]
        st = sum(q for _, q in offer)
        if centre + st < READY_MIN_QTY: continue
        cat = re.sub(r'\s+', ' ', str(r[col['Item Category Name']] or '')).strip()
        locs = ([f'GUDANG {centre}'] if centre else []) + [f'{s} {q}' for s, q in sorted(offer, key=lambda x: -x[1])]
        out.append([str(code), name, group(cat), cat.title() if cat else '', sup, price, centre + st, centre, st, '; '.join(locs), as_of])
    return sorted(out, key=lambda r: (-r[6] * r[5], r[1]))


if __name__ == '__main__':
    src = sys.argv[1] if len(sys.argv) > 1 else newest()
    rows = ready(src)
    dst = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'ready_stock.csv')
    with open(dst, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(HEADER); w.writerows(rows)
    print('read', os.path.basename(src), '| wrote ready_stock.csv', len(rows), 'titles,', sum(r[6] for r in rows), 'copies, as of', rows[0][-1] if rows else '?')
