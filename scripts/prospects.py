"""New-account list for the reseller team: data/reseller_prospects.csv.

This file is public, like everything in data/. It holds only names, public links, city and segment:
no sales, no contact people, phone numbers, emails, message drafts or internal notes.

  python scripts/prospects.py build TRACKER.xlsx    first load from the Reseller Tracker workbook
  python scripts/prospects.py merge NEW.csv         add the weekly scan's finds (name,segment,city,link,priority)

merge skips anything already listed, any existing customer (data/resellers.csv, kept private on this Mac)
and any shop on the pirate watch (data/prospects_block.txt, also private).
"""
import csv, datetime, os, re, sys
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'reseller_prospects.csv')
BLOCK = os.path.join(ROOT, 'data', 'prospects_block.txt')
CUSTOMERS = os.path.join(ROOT, 'data', 'resellers.csv')
FIELDS = ['name', 'segment', 'sub_segment', 'city', 'platform', 'link', 'priority', 'source', 'first_seen']
PLATFORMS = [('instagram.', 'Instagram'), ('tokopedia.', 'Tokopedia'), ('shopee.', 'Shopee'), ('tiktok.', 'TikTok'), ('threads.', 'Threads'),
             ('facebook.', 'Facebook'), ('fb.', 'Facebook'), ('x.com', 'X'), ('twitter.', 'X')]
PRIVATE_LINK = re.compile(r'wa\.me|whatsapp|mailto:|t\.me', re.I)


def norm(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def clean_link(text):
    for u in re.findall(r'https?://[^\s,;)]+', text or ''):
        if not PRIVATE_LINK.search(u): return u.rstrip('.')
    return ''


def platform(link):
    host = urlparse(link).netloc.lower().removeprefix('www.')
    if not host: return ''
    for key, name in PLATFORMS:
        if host.startswith(key) or host == key: return name
    return 'Website'


def link_key(link):
    p = urlparse(link)
    return (p.netloc.lower().removeprefix('www.') + p.path.rstrip('/').lower()) if link else ''


def read():
    if not os.path.exists(OUT): return []
    return list(csv.DictReader(open(OUT, encoding='utf-8')))


def write(rows):
    rows.sort(key=lambda r: (r['first_seen'], r['priority'], r['name'].lower()))
    with open(OUT, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, FIELDS); w.writeheader(); w.writerows(rows)


def blocked():
    names = set()
    if os.path.exists(BLOCK): names |= {norm(l) for l in open(BLOCK, encoding='utf-8') if l.strip()}
    if os.path.exists(CUSTOMERS):
        for r in csv.DictReader(open(CUSTOMERS, encoding='utf-8')):
            names |= {norm(r.get('shop')), norm(r.get('account'))}
    names.discard('')
    return names


def build(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    pirates = [r[0] for r in wb['Pirate watch | Pantau bajakan'].iter_rows(values_only=True)][1:]
    with open(BLOCK, 'w', encoding='utf-8') as f: f.write('\n'.join(str(p) for p in pirates if p) + '\n')
    block = {norm(str(p)) for p in pirates if p}
    out, seen = [], set()
    for sheet, tier in (('Tracker | Daftar kerja', None), ('Parking | Antrean', 'Cek dulu')):
        rows = list(wb[sheet].iter_rows(values_only=True))
        ix = {str(h).split('\n')[0]: i for i, h in enumerate(rows[0])}
        for r in rows[1:]:
            if not r[0] or not str(r[ix['Type']]).startswith('Prospect'): continue
            name = str(r[ix['Name']] or '').strip(); key = norm(name)
            if not key or key in block or key in seen: continue
            seen.add(key)
            link = clean_link(str(r[ix['Contact (channel and link)']] or ''))
            out.append({'name': name, 'segment': str(r[ix['Segment']] or '').split(' / ')[0], 'sub_segment': str(r[ix['Sub-segment']] or '').split(' / ')[0],
                        'city': str(r[ix['City']] or '').strip(), 'platform': platform(link), 'link': link, 'priority': tier or str(r[ix['Priority']] or ''),
                        'source': 'Tracker Okt 2026', 'first_seen': '2026-10-22'})
    write(out); print('prospects', len(out))


def merge(path):
    rows = read(); names = {norm(r['name']) for r in rows}; links = {link_key(r['link']) for r in rows if r['link']}
    block = blocked(); today = datetime.date.today().isoformat(); added = skipped = 0
    for r in csv.DictReader(open(path, encoding='utf-8')):
        name = (r.get('name') or '').strip(); link = clean_link(r.get('link') or ''); key = norm(name)
        if not key or not link or key in names or key in block or link_key(link) in links: skipped += 1; continue
        rows.append({'name': name, 'segment': (r.get('segment') or 'Online reseller').strip(), 'sub_segment': (r.get('sub_segment') or '').strip(), 'city': (r.get('city') or '').strip(),
                     'platform': platform(link), 'link': link, 'priority': (r.get('priority') or 'Cek dulu').strip(), 'source': 'Scan mingguan', 'first_seen': today})
        names.add(key); links.add(link_key(link)); added += 1
    write(rows); print(f'added {added}, skipped {skipped} (already listed, existing customer, pirate watch or no link); total {len(rows)}')


if __name__ == '__main__':
    {'build': build, 'merge': merge}[sys.argv[1]](sys.argv[2])
