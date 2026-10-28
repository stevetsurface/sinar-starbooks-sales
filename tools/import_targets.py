"""Convert the "Target Wonder Bookstore 2026" workbook into data/targets.csv for the dashboard.

Usage: python3 tools/import_targets.py "Target Wonder Bookstore 2026.xlsx"
Each target row becomes one line per month: month, location (Jubelio location code), line, target.
line = pos (in-store till), shopee (Shopee orders shipped from that store), coffee (Berawa coffee bar),
st (the "(ST)" rows: not yet mapped to a Jubelio channel). Total rows are skipped; the dashboard adds up.
"""
import csv, datetime, os, re, sys
from openpyxl import load_workbook

STORES = [('hublife', 'HUBLIFE'), ('astha', 'ASHTA'), ('ashta', 'ASHTA'), ('tsm jakarta', 'JKT-TSM'), ('bali brawa', 'BALI-BERAWA'), ('brawa', 'BALI-BERAWA'), ('tsm bali', 'BALI-TSM'), ('pim', 'PIM')]


def classify(label, block_loc):
    t = label.lower()
    if t.startswith('total'): return None
    # a row names its store, or belongs to the block it sits in (e.g. "Shopee Wonder TSM" under TSM Jakarta)
    loc = next((code for key, code in STORES if key in t), None) or block_loc
    if not loc: return None
    if t.startswith('pameran'): loc = 'PAMERAN ' + loc
    line = 'shopee' if 'shopee' in t else 'coffee' if 'coffe' in t else 'st' if re.search(r'\(?\bst\)?\s*$', t) else 'pos'
    return loc, line


def main(path):
    ws = load_workbook(path, data_only=True).active
    head = None
    for r in ws.iter_rows(min_row=1, max_row=15):
        if any(isinstance(c.value, datetime.datetime) for c in r): head = r; break
    months = {c.column: c.value.strftime('%Y-%m') for c in head if isinstance(c.value, datetime.datetime)}
    out = []; block = None
    for r in ws.iter_rows(min_row=head[0].row + 1):
        label = next((c.value for c in r if isinstance(c.value, str)), None)
        if not label: continue
        if label.lower().startswith('total'): block = None; continue
        k = classify(label.strip(), block)
        if not k: continue
        if block is None: block = k[0].replace('PAMERAN ', '')
        for c in r:
            if c.column in months and isinstance(c.value, (int, float)) and c.value:
                out.append([months[c.column], k[0], k[1], round(c.value), label.strip()])
    dst = os.path.join(os.path.dirname(__file__), '..', 'data', 'targets.csv')
    with open(dst, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(['month', 'location', 'line', 'target', 'source_row']); w.writerows(sorted(out))
    print('wrote targets.csv', len(out), 'rows')


if __name__ == '__main__':
    main(sys.argv[1])
