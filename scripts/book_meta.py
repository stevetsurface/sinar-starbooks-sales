"""Covers and synopses for the reseller lists (ready stock, clearance, pre-order), looked up by ISBN and cached.

data/book_meta.csv keeps one row per ISBN, so each title is looked up once; misses are retried after RETRY_DAYS.
Google Books gives the cover and the publisher's description; it needs a free API key (repo secret GOOGLE_BOOKS_KEY),
without one it refuses requests, so only Open Library covers are filled in. Rows checked without the key are looked up
again once the key exists. Google's free quota is 1,000 requests a day, hence PER_RUN.
Run by the daily sync:  python scripts/book_meta.py
"""
import csv, html, json, os, re, sys, time, urllib.error, urllib.request
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'data', 'book_meta.csv')
HEADER = ['isbn', 'cover', 'synopsis', 'source', 'google_checked', 'checked']
KEY = os.environ.get('GOOGLE_BOOKS_KEY', '').strip()
PER_RUN = 900              # stays under Google's 1,000 a day
RETRY_DAYS = 30            # a title with nothing found is tried again after this long (new titles get covers late)
SYNOPSIS_MAX = 600         # characters kept, cut at a sentence end where possible
LISTS = [('preorder.csv', 'isbn'), ('ready_stock.csv', 'item_code'), ('clearance.csv', 'item_code')]


def wanted():
    seen = []
    for f, col in LISTS:
        p = os.path.join(ROOT, 'data', f)
        if not os.path.exists(p): continue
        with open(p, encoding='utf-8') as fh:
            for r in csv.DictReader(fh):
                i = (r.get(col) or '').strip()
                if re.fullmatch(r'97[89]\d{10}', i) and i not in seen: seen.append(i)
    return seen


def get(url, head=False):
    req = urllib.request.Request(url, method='HEAD' if head else 'GET', headers={'User-Agent': 'sinar-starbooks-dashboard'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status if head else json.load(r)


def short(text):
    t = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', text or ''))).strip()
    if len(t) <= SYNOPSIS_MAX: return t
    cut = t[:SYNOPSIS_MAX]
    end = max(cut.rfind('. '), cut.rfind('! '), cut.rfind('? '))
    return cut[:end + 1] if end > SYNOPSIS_MAX // 2 else cut.rsplit(' ', 1)[0] + '…'


def google(isbn):
    j = get(f'https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}&key={KEY}')
    v = ((j.get('items') or [{}])[0]).get('volumeInfo', {})
    img = (v.get('imageLinks') or {})
    cover = (img.get('thumbnail') or img.get('smallThumbnail') or '').replace('http://', 'https://').replace('&edge=curl', '')
    return cover, short(v.get('description'))


def openlibrary(isbn):
    """Cover by Open Library's cover id: links by ISBN are rate-limited for the people viewing the page, links by id are not."""
    try: d = get(f'https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data')
    except Exception: return ''  # timeouts and outages: the title is tried again after RETRY_DAYS
    return ((d.get('ISBN:' + isbn) or {}).get('cover') or {}).get('medium', '')


def save(cache):
    with open(CACHE, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, HEADER); w.writeheader(); w.writerows(sorted(cache.values(), key=lambda r: r['isbn']))


def main():
    cache = {}
    if os.path.exists(CACHE):
        with open(CACHE, encoding='utf-8') as f: cache = {r['isbn']: r for r in csv.DictReader(f)}
    today = date.today()
    def due(i):
        r = cache.get(i)
        if not r: return True
        if KEY and r['google_checked'] != 'y': return True
        if '/b/isbn/' in r['cover']: return True  # older rate-limited link, swap for the cover-id one
        return not r['cover'] and date.fromisoformat(r['checked']) <= today - timedelta(days=RETRY_DAYS)
    todo = [i for i in wanted() if due(i)][:PER_RUN if KEY else None]  # the cap is for Google's quota only
    found = 0
    for n, i in enumerate(todo):
        old = cache.get(i, {})
        cover, syn, src = '', '', []
        if KEY:
            try:
                cover, syn = google(i)
                if cover or syn: src.append('Google Books')
            except urllib.error.HTTPError as e:
                if e.code == 429: print('Google quota reached after', n, 'lookups; the rest wait for the next run', file=sys.stderr); break
                print('google', i, e, file=sys.stderr)
            except Exception as e: print('google', i, e, file=sys.stderr)
        if not cover:
            cover = openlibrary(i)
            if cover: src.append('Open Library')
        cover, syn = cover or (old.get('cover', '') if '/b/isbn/' not in old.get('cover', '') else ''), syn or old.get('synopsis', '')
        found += bool(cover)
        cache[i] = {'isbn': i, 'cover': cover, 'synopsis': syn, 'source': ' + '.join(src) or old.get('source', ''),
                    'google_checked': 'y' if KEY else old.get('google_checked', ''), 'checked': today.isoformat()}
        time.sleep(0.1)
        if n % 100 == 99: save(cache)
    save(cache)
    rows = cache.values()
    print(f'book meta: looked up {len(todo)} ({found} with a cover), cache {len(cache)} ISBNs,',
          sum(1 for r in rows if r['cover']), 'covers,', sum(1 for r in rows if r['synopsis']), 'synopses', '' if KEY else '(no GOOGLE_BOOKS_KEY: Open Library covers only)')


if __name__ == '__main__':
    main()
