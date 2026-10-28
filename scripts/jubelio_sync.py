#!/usr/bin/env python3
"""Daily Jubelio export for the Wonder Bookstore / Sinar Starbooks dashboard.

Logs in to Jubelio with JUBELIO_EMAIL / JUBELIO_PASSWORD (repo secrets), pulls
sales orders (since 2025-10-01), order details (last 90 days, cached), and the
inventory alert lists, then writes the CSV files the dashboard reads into data/.
"""
import csv, gzip, io, json, os, re, sys, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT = os.path.join(os.path.dirname(__file__), '..', 'data')
CACHE = os.path.join(os.path.dirname(__file__), '..', 'cache')
START = os.environ.get('SYNC_START', '2025-10-01')
WIB = timezone(timedelta(hours=7))
BASES = ['https://api2.jubelio.com', 'https://open.jubelio.com/core-api']
TOKEN = None
BASE = None


def http(method, url, body=None, token=None, tries=4):
    data = json.dumps(body).encode() if body is not None else None
    for i in range(tries):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header('Content-Type', 'application/json')
        if token:
            req.add_header('Authorization', token)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < tries - 1:
                time.sleep(2 * (i + 1)); continue
            raise RuntimeError(f'{method} {url} -> {e.code} {e.read()[:200]!r}')
        except Exception:
            if i < tries - 1:
                time.sleep(2 * (i + 1)); continue
            raise


def login():
    global TOKEN, BASE
    email, pw = os.environ['JUBELIO_EMAIL'], os.environ['JUBELIO_PASSWORD']
    r = http('POST', 'https://api2.jubelio.com/login', {'email': email, 'password': pw})
    TOKEN = r['token']
    for b in BASES:  # pick the first base that answers with this token
        try:
            http('GET', b + '/sales/orders/?page=1&pageSize=1', token=TOKEN, tries=1)
            BASE = b; break
        except Exception as e:
            print('base failed', b, e, file=sys.stderr)
    if not BASE:
        raise SystemExit('No Jubelio API base accepted the token')
    print('Using', BASE)


def get(path):
    return http('GET', BASE + path, token=TOKEN)


# ---------------------------------------------------------------- orders
def pull_orders(frm, to):
    q = f'transactionDateFrom={frm}&transactionDateTo={to}&sortBy=salesorder_id&sortDirection=ASC'
    first = get(f'/sales/orders/?page=1&pageSize=200&{q}')
    n = (first['totalCount'] + 199) // 200
    rows = list(first['data'])
    with ThreadPoolExecutor(6) as ex:
        for d in ex.map(lambda p: get(f'/sales/orders/?page={p}&pageSize=200&{q}'), range(2, n + 1)):
            rows.extend(d['data'])
    return rows


def month_windows(start, end):
    y, m = int(start[:4]), int(start[5:7])
    while (y, m) <= (end.year, end.month):
        s = datetime(y, m, 1, tzinfo=WIB)
        m2, y2 = (m + 1, y) if m < 12 else (1, y + 1)
        e = datetime(y2, m2, 1, tzinfo=WIB) - timedelta(seconds=1)
        yield s.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), e.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        y, m = y2, m2


def brand(s):
    s = (s or '').upper()
    if 'SINAR' in s or 'WOE-70018' in s: return 'Sinar Starbooks'
    if 'KIKKERLAND' in s: return 'Kikkerland'
    return 'Wonder Bookstore'


def chan(c):
    c = (c or '').upper()
    if c.startswith('SHOP | TOKOPEDIA') or 'TIKTOK' in c: return 'TikTok Shop'
    return {'SHOPEE': 'Shopee', 'TOKOPEDIA': 'Tokopedia', 'JUBELIO-POS': 'In-store POS', 'LAZADA': 'Lazada', 'BLIBLI': 'Blibli', 'INTERNAL': 'Internal / B2B'}.get(c, c.title())


BAD = {'CANCELED', 'REQUEST_CANCEL', 'RETURNED'}
def is_bad(o): return o.get('internal_status') in BAD or o.get('is_canceled') is True
def wib(t): return datetime.fromisoformat(t.replace('Z', '+00:00')).astimezone(WIB)


SKIP = re.compile(r'SHOPPING BAG|PACKING|KARDUS|BUBBLE|PAPER BAG|PAPERBAG|TAS BELANJA|GIFTWRAP|MATERAI|CREDIT VOUCHER|^PESANAN|PITA KADO')
def cafe(code, name): return (name or '').strip().upper().startswith('*') or (code or '').startswith('CF')
def skip_item(code, name): return cafe(code, name) or bool(SKIP.search((name or '').upper())) or code == '123'


def basket_rows(recent, det):
    """Per day/brand/channel basket metrics from cached order details (last 90 days).

    units: sum of item qty; a line with no qty but an amount counts as 1 (Jubelio POS lines
    carry qty 0). Customers: contact_id > 0 only (-1 etc. = walk-in / anonymous). Returning =
    the customer already had an earlier non-cancelled order inside the detail window."""
    rec = sorted((o for o in recent if not is_bad(o) and str(o['salesorder_id']) in det), key=lambda o: o['transaction_date'])
    seen = set(); BK = defaultdict(lambda: [0, 0.0, 0, 0.0, 0.0, 0, 0, 0, 0.0, 0.0])
    for o in rec:
        d = det[str(o['salesorder_id'])]
        k = (wib(o['transaction_date']).date().isoformat(), brand(o.get('store_name')), chan(o.get('channel_name')))
        a = BK[k]; a[0] += 1; a[3] += d['sub']; a[9] += float(o.get('grand_total') or d['gt'])
        for iid, code, name, qty, amt, cx in d['items']:
            if cx or skip_item(code, name): continue
            a[1] += qty if qty > 0 else (1 if amt > 0 else 0); a[2] += 1
        if d['disc'] > 0: a[4] += d['disc']; a[5] += 1
        c = d.get('cust')
        if c is not None and c > 0:
            a[6] += 1
            key = (k[1], k[2] == 'In-store POS', c)
            if key in seen: a[7] += 1; a[8] += float(o.get('grand_total') or d['gt'])
            seen.add(key)
    return [list(k) + [v[0], round(v[1], 2), v[2], round(v[3]), round(v[9]), round(v[4]), v[5], v[6], v[7], round(v[8])] for k, v in sorted(BK.items())]


BASKET_HEADER = ['date', 'brand', 'channel', 'orders', 'units', 'lines', 'gross', 'revenue', 'discount_amount', 'discounted_orders', 'identified_orders', 'returning_orders', 'returning_revenue']


def cancel_recovery(recent, det):
    """Cancelled / returned orders in the detail window, and whether the same customer bought again within 7 days.
    Returns (by brand+channel+status, by shipping location, by title)."""
    good = defaultdict(list)
    for o in recent:
        if is_bad(o): continue
        c = (det.get(str(o['salesorder_id'])) or {}).get('cust')
        if c is not None and c > 0: good[c].append(wib(o['transaction_date']))
    for v in good.values(): v.sort()
    REC = defaultdict(lambda: [0, 0.0, 0, 0.0]); LOC = defaultdict(lambda: [0, 0.0, 0, 0.0]); TIT = defaultdict(lambda: [0, 0.0, 0.0])
    for o in recent:
        if not is_bad(o): continue
        d = det.get(str(o['salesorder_id']))
        if not d: continue
        t = wib(o['transaction_date']); b = brand(o.get('store_name')); c = chan(o.get('channel_name')); st = o.get('internal_status') or 'CANCELED'
        loc = (o.get('location_name') or '-').strip(); val = d['sub']; cust = d.get('cust')
        again = bool(cust and cust > 0 and any(t < g <= t + timedelta(days=7) for g in good.get(cust, [])))
        for a in (REC[(b, c, st)], LOC[(loc, c, st)]):
            a[0] += 1; a[1] += val
            if again: a[2] += 1; a[3] += val
        for iid, code, name, qty, amt, cx in d['items']:
            if skip_item(code, name): continue
            u = qty if qty > 0 else (1 if amt > 0 else 0)
            tt = TIT[(code or '', clean(name), b, c)]; tt[0] += 1; tt[1] += u; tt[2] += amt
    rec = [list(k) + [v[0], round(v[1]), v[2], round(v[3])] for k, v in sorted(REC.items())]
    loc = [list(k) + [v[0], round(v[1]), v[2], round(v[3])] for k, v in sorted(LOC.items())]
    tit = [list(k) + [v[0], round(v[1], 1), round(v[2])] for k, v in sorted(TIT.items(), key=lambda kv: -kv[1][0])[:300]]
    return rec, loc, tit


def store_daily(recent, det):
    """Per day and store (POS orders): tickets, units, lines, identified customers, discounted tickets, revenue."""
    S = defaultdict(lambda: [0, 0.0, 0, 0, 0, 0.0, 0.0])
    for o in recent:
        if is_bad(o) or chan(o.get('channel_name')) != 'In-store POS': continue
        d = det.get(str(o['salesorder_id']))
        if not d: continue
        a = S[(wib(o['transaction_date']).date().isoformat(), (o.get('location_name') or '-').strip())]
        a[0] += 1; a[6] += float(o.get('grand_total') or d['gt'])
        if d.get('cust') is not None and d['cust'] > 0: a[3] += 1
        if d['disc'] > 0: a[4] += 1; a[5] += d['disc']
        for iid, code, name, qty, amt, cx in d['items']:
            if cx or skip_item(code, name) or amt <= 0: continue
            a[1] += qty if qty > 0 else 1; a[2] += 1
    return [list(k) + [v[0], round(v[1], 1), v[2], v[3], v[4], round(v[5]), round(v[6])] for k, v in sorted(S.items())]


ALERT_RULES = {  # thresholds the morning alerts use; edit here, no code changes needed
    'store_drop_medium': 0.20, 'store_drop_high': 0.35, 'store_min_revenue': 5_000_000,
    'cancel_rate_medium': 0.12, 'cancel_rate_high': 0.20, 'cancel_min_orders': 30,
    'runout_days': 7, 'oversold_lines_medium': 40, 'oversold_lines_high': 80,
    'stale_hours_high': 36, 'keep_days': 14,
}


def alerts_from_data(now):
    """Reads the CSVs just written and keeps a rolling 14-day alerts.csv (today's rows are recomputed each run)."""
    R = ALERT_RULES; today = now.date().isoformat(); y = (now.date() - timedelta(days=1))
    def rd(name):
        pth = os.path.join(OUT, name)
        return list(csv.DictReader(open(pth, encoding='utf-8'))) if os.path.exists(pth) else []
    out = []
    def add(rule, key, sev, tab, tid, ten, did, den):
        out.append([f'{rule}:{key}:{today}', today, sev, rule, key, tab, tid, ten, did, den])
    sd = rd('sales_daily_detail.csv')
    d7 = {(y - timedelta(days=i)).isoformat() for i in range(7)}; p7 = {(y - timedelta(days=7 + i)).isoformat() for i in range(7)}
    # stores: POS revenue last 7 days vs the 7 before
    cur = defaultdict(float); prv = defaultdict(float)
    for r in sd:
        if r['channel'] != 'In-store POS': continue
        if r['date'] in d7: cur[r['location']] += float(r['revenue'])
        elif r['date'] in p7: prv[r['location']] += float(r['revenue'])
    for loc, pv in prv.items():
        cv = cur.get(loc, 0.0)
        if pv < R['store_min_revenue']: continue
        drop = 1 - cv / pv
        if drop >= R['store_drop_medium']:
            sev = 'high' if drop >= R['store_drop_high'] else 'medium'
            add('store_drop', loc, sev, 'toko', f'Toko {loc} turun {drop:.0%} minggu ini', f'{loc} store down {drop:.0%} this week',
                f'Penjualan kasir 7 hari terakhir Rp {cv/1e6:.1f} jt vs Rp {pv/1e6:.1f} jt pada 7 hari sebelumnya.', f'POS sales last 7 days Rp {cv/1e6:.1f}M vs Rp {pv/1e6:.1f}M the 7 days before.')
    # cancel rate by channel, last 7 days
    co = defaultdict(lambda: [0, 0])
    for r in sd:
        if r['date'] in d7: co[r['channel']][0] += int(r['orders']); co[r['channel']][1] += int(r['canceled'])
    for ch, (o, x) in co.items():
        if o + x < R['cancel_min_orders']: continue
        rate = x / (o + x)
        if rate >= R['cancel_rate_medium']:
            sev = 'high' if rate >= R['cancel_rate_high'] else 'medium'
            add('cancel_rate', ch, sev, 'finance', f'Pembatalan {ch} {rate:.0%} minggu ini', f'{ch} cancellations at {rate:.0%} this week',
                f'{x} dari {o + x} pesanan 7 hari terakhir dibatalkan atau diretur.', f'{x} of {o + x} orders in the last 7 days cancelled or returned.')
    # bestsellers about to run out
    ro = [r for r in rd('stock_runout.csv') if float(r['days_left']) <= R['runout_days']]
    if ro:
        names = ', '.join(r['item_name'][:40] for r in ro[:3]) + (' …' if len(ro) > 3 else '')
        add('runout', 'all', 'high', 'stock', f'{len(ro)} barang laris habis dalam {R["runout_days"]} hari', f'{len(ro)} fast sellers run out within {R["runout_days"]} days', names, names)
    # oversold lines
    ov = rd('stock_oversold.csv')
    if len(ov) >= R['oversold_lines_medium']:
        sev = 'high' if len(ov) >= R['oversold_lines_high'] else 'medium'
        add('oversold', 'all', sev, 'stock', f'{len(ov)} baris oversold', f'{len(ov)} oversold lines', 'Terjual melebihi stok tersedia; cek fisik dan stok marketplace.', 'Sold beyond available stock; check physical and marketplace stock.')
    # transfers ready
    ts = rd('transfer_summary.csv')
    hi = sum(int(r['sku_high']) for r in ts); qty = sum(int(r['qty_transfer']) for r in ts)
    if hi:
        add('transfers', 'all', 'low', 'stock', f'{hi} SKU prioritas tinggi siap ditransfer', f'{hi} high-priority SKUs ready to transfer', f'Total usulan {qty} pcs. File transfer ada di tab Stok.', f'{qty} pcs suggested in total. The transfer file is on the Stock tab.')
    # sync health
    sn = {r['source']: r for r in rd('snapshots.csv')}
    lo = sn.get('sales', {}).get('last_order_at')
    if lo:
        age = (now - datetime.fromisoformat(lo.replace('Z', '+00:00'))).total_seconds() / 3600
        if age >= R['stale_hours_high']:
            add('stale', 'all', 'high', 'ringkasan', f'Tidak ada pesanan baru {age:.0f} jam', f'No new orders for {age:.0f} h', 'Jubelio mungkin tidak terhubung; cek sinkronisasi.', 'Jubelio may be disconnected; check the sync.')
    # rolling window: keep earlier days, replace today
    keep = [r for r in rd('alerts.csv') if r.get('date') and r['date'] != today and r['date'] >= (now.date() - timedelta(days=R['keep_days'])).isoformat()]
    hdr = ['id', 'date', 'severity', 'rule', 'key', 'tab', 'title_id', 'title_en', 'detail_id', 'detail_en']
    rows = out + [[r[h] for h in hdr] for r in keep]
    order = {'high': 0, 'medium': 1, 'low': 2}
    rows.sort(key=lambda r: (r[1], -order.get(r[2], 3)), reverse=True)
    write('alerts.csv', hdr, rows)


def item_group(code, name):
    nm = (name or '').upper()
    if cafe(code, name): return 'Kafe'
    if re.search(r'KOMIK|MANGA|\bVOL\.?\s*\d|OMNIBUS|GRAPHIC NOVEL', nm): return 'Komik & manga'
    isbn = bool(re.match(r'^97[89]\d{10}$', code or ''))
    if isbn and re.search(r'BOARD BOOK|STICKER BOOK|SOUND BOOK|COLOU?RING|PEPPA|BLUEY|DISNEY|MY FIRST|BABY|TODDLER|DOG MAN|WIMPY KID|BAD GUYS', nm): return 'Buku anak'
    if isbn: return 'Buku umum'
    return 'Alat tulis & gift'


def purchases(since='2025-01-01'):
    """Purchase orders and bills -> supplier per item, last PO date, measured lead time per supplier.
    Cached in cache/po.json.gz WITHOUT prices (the repo is public)."""
    cpath = os.path.join(CACHE, 'po.json.gz')
    cache = json.load(gzip.open(cpath, 'rt')) if os.path.exists(cpath) else {}
    pos, page = [], 1
    while True:
        r = get(f'/purchase/orders/?page={page}&pageSize=200&sortBy=transaction_date&sortDirection=DESC')
        data = r.get('data') or []
        pos += data
        if len(data) < 200 or any((x.get('transaction_date') or '')[:10] < since for x in data): break
        page += 1
    pos = [x for x in pos if (x.get('transaction_date') or '')[:10] >= since]
    need = [x for x in pos if str(x['purchaseorder_id']) not in cache or cache[str(x['purchaseorder_id'])].get('lm') != x.get('last_modified')]
    print('purchase orders', len(pos), 'details to fetch', len(need))
    def fetch(x):
        try: d = get(f"/purchase/orders/{x['purchaseorder_id']}")
        except Exception: return x, None
        return x, [[it.get('item_id'), float(it.get('qty_in_base') or it.get('qty') or 0)] for it in d.get('items') or []]
    with ThreadPoolExecutor(6) as ex:
        for x, items in ex.map(fetch, need):
            if items is None: continue
            cache[str(x['purchaseorder_id'])] = {'lm': x.get('last_modified'), 's': (x.get('supplier_name') or '').strip(), 'd': (x.get('transaction_date') or '')[:10], 'it': items}
    keep = {str(x['purchaseorder_id']) for x in pos}
    cache = {k: v for k, v in cache.items() if k in keep}
    json.dump(cache, gzip.open(cpath, 'wt'))
    # bills -> first bill date per PO
    first_bill, page = {}, 1
    while True:
        r = get(f'/purchase/bills/?page={page}&pageSize=200&sortBy=transaction_date&sortDirection=DESC')
        data = r.get('data') or []
        for b in data:
            po = b.get('purchaseorder_id'); d = (b.get('transaction_date') or '')[:10]
            if po and d and (str(po) not in first_bill or d < first_bill[str(po)]): first_bill[str(po)] = d
        if len(data) < 200 or any((b.get('transaction_date') or '')[:10] < since for b in data): break
        page += 1
    supplier_of, last_po, lead, po_count = {}, {}, defaultdict(list), defaultdict(int)
    yr_ago = (datetime.now(WIB).date() - timedelta(days=365)).isoformat()
    for k, v in sorted(cache.items(), key=lambda kv: kv[1]['d']):
        for iid, q in v['it']:
            supplier_of[iid] = v['s']; last_po[iid] = v['d']
        if v['d'] >= yr_ago: po_count[v['s']] += 1
        if k in first_bill:
            days = (datetime.fromisoformat(first_bill[k]) - datetime.fromisoformat(v['d'])).days
            if 5 <= days <= 240: lead[v['s']].append(days)  # same-day bills mean the PO was raised at receipt: not a lead time
    import statistics
    lead_by = {s: (round(statistics.median(v)), len(v)) for s, v in lead.items()}
    print('suppliers', len(po_count), 'with measured lead time', sum(1 for v in lead_by.values() if v[1] >= 2))
    return supplier_of, last_po, lead_by, dict(po_count)


SCOUT_SHEET = os.environ.get('SCOUT_SHEET_CSV') or 'https://docs.google.com/spreadsheets/d/1dKDvrd-9HdAj4EMxLiV4T3Ahk9kLe91b1uDXweS7VIw/export?format=csv'


def scout_picks():
    """Booky Scout writes its weekly picks to a Google Sheet; keep the latest week and add our own stock
    and 90-day sales per ISBN from catalog.csv, so the dashboard shows each pick next to what we already carry."""
    try:
        with urllib.request.urlopen(SCOUT_SHEET, timeout=60) as r:
            text = r.read().decode('utf-8-sig')
    except urllib.error.HTTPError as e:
        print(f'scout sheet not readable ({e.code}); set it to "anyone with the link can view". Keeping the previous file.', file=sys.stderr)
        return
    rows = [r for r in csv.DictReader(io.StringIO(text)) if (r.get('title') or '').strip()]
    status = 'ok' if rows else 'empty'
    latest = max((r.get('week_of') or '').strip() for r in rows) if rows else ''
    rows = [r for r in rows if (r.get('week_of') or '').strip() == latest]
    cat = {}
    cpath = os.path.join(OUT, 'catalog.csv')
    if os.path.exists(cpath):
        for c in csv.DictReader(open(cpath, encoding='utf-8')):
            cat[re.sub(r'\D', '', c['item_code'] or '')] = c
    out = []
    for r in rows:
        isbn = re.sub(r'\D', '', r.get('isbn') or '')
        c = cat.get(isbn) if isbn else None
        out.append([(r.get(k) or '').strip() for k in ['week_of', 'side', 'rank', 'urgency', 'title', 'author', 'publisher', 'isbn', 'why', 'trending_in', 'early_buy', 'confidence', 'source_url']]
                   + (['ya', c['available'], c['units_90d'], c['available_by_location']] if c else ['tidak' if isbn else '', '', '', '']))
    write('scout_picks.csv', ['week_of', 'side', 'rank', 'urgency', 'title', 'author', 'publisher', 'isbn', 'why', 'trending_in', 'early_buy', 'confidence', 'source_url',
                              'in_catalog', 'available', 'units_90d', 'available_by_location'], out)
    print('scout picks', status, latest, len(out))


def write(name, header, rows):
    with open(os.path.join(OUT, name), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(header); w.writerows(rows)
    print('wrote', name, len(rows))


def clean(s): return re.sub(r'[….,]{4,}', '', re.sub(r'\s+', ' ', str(s or ''))).strip()


def main():
    os.makedirs(OUT, exist_ok=True); os.makedirs(CACHE, exist_ok=True)
    login()
    now = datetime.now(WIB)
    orders = []
    for s, e in month_windows(START, now):
        orders.extend(pull_orders(s, e))
    orders = list({o['salesorder_id']: o for o in orders}.values())
    print('orders', len(orders))

    # sales_daily_detail
    D = defaultdict(lambda: [0, 0.0, 0])
    for o in orders:
        k = (wib(o['transaction_date']).date().isoformat(), brand(o.get('store_name')), chan(o.get('channel_name')), o.get('location_name') or '-')
        if is_bad(o): D[k][2] += 1
        else: D[k][0] += 1; D[k][1] += float(o.get('grand_total') or 0)
    write('sales_daily_detail.csv', ['date', 'brand', 'channel', 'location', 'orders', 'revenue', 'canceled'], [list(k) + [v[0], round(v[1]), v[2]] for k, v in sorted(D.items())])

    since = (now - timedelta(days=90)).date().isoformat()
    HD = defaultdict(lambda: [0, 0.0])
    for o in orders:
        if is_bad(o): continue
        t = wib(o['transaction_date'])
        if t.date().isoformat() < since: continue
        hk = (brand(o.get('store_name')), 'store' if chan(o.get('channel_name')) == 'In-store POS' else 'online', (o.get('location_name') or '-').strip(), t.weekday(), t.hour)
        HD[hk][0] += 1; HD[hk][1] += float(o.get('grand_total') or 0)
    write('hour_dow.csv', ['brand', 'kind', 'location', 'dow', 'hour', 'orders', 'revenue'], [list(k) + [v[0], round(v[1])] for k, v in HD.items()])

    # order details (cached)
    cpath = os.path.join(CACHE, 'details.json.gz')
    det = json.load(gzip.open(cpath, 'rt')) if os.path.exists(cpath) else {}
    recent = [o for o in orders if wib(o['transaction_date']).date().isoformat() >= since]
    need = [o['salesorder_id'] for o in recent if str(o['salesorder_id']) not in det or det[str(o['salesorder_id'])].get('lm') != o.get('last_modified')]
    print('details to fetch', len(need))
    def fetch(i):
        try:
            d = get(f'/sales/orders/{i}')
        except Exception as e:
            return i, None
        return i, {'sub': float(d.get('sub_total') or 0), 'disc': float(d.get('total_disc') or 0) + float(d.get('voucher_amount') or 0) + float(d.get('add_disc') or 0),
                   'fee': float(d.get('service_fee') or 0), 'ship': float(d.get('shipping_cost') or 0), 'gt': float(d.get('grand_total') or 0),
                   'cr': d.get('mp_cancel_reason') or (d.get('cancel_reason') if d.get('cancel_reason') not in (None, 'false') else None), 'cust': d.get('contact_id'),
                   'items': [[it.get('item_id'), it.get('item_code'), it.get('item_name'), float(it.get('qty') or it.get('qty_in_base') or it.get('quantity') or 0), float(it.get('amount') or 0), 1 if it.get('is_canceled_item') else 0] for it in d.get('items') or []]}
    lm = {o['salesorder_id']: o.get('last_modified') for o in recent}
    with ThreadPoolExecutor(8) as ex:
        for i, d in ex.map(fetch, need):
            if d:
                d['lm'] = lm.get(i)
                det[str(i)] = d
    keep = {str(o['salesorder_id']) for o in recent}
    det = {k: v for k, v in det.items() if k in keep}
    json.dump(det, gzip.open(cpath, 'wt'))

    # item master: prices + names
    price = {}
    first = get('/inventory/items/?page=1&pageSize=200'); n = (first['totalCount'] + 199) // 200
    pages = [first] + [get(f'/inventory/items/?page={p}&pageSize=200') for p in range(2, n + 1)]
    master, bundles = {}, set()
    for pg in pages:
        for g in pg.get('data', []):
            for v in g.get('variants') or []:
                price[v['item_id']] = float(v.get('sell_price') or g.get('sell_price') or 0)
                master[v['item_id']] = (v.get('item_code') or g.get('item_code') or '', clean(v.get('item_name') or g.get('item_name') or ''))
                if g.get('is_bundle') or v.get('is_bundle'): bundles.add(v['item_id'])

    group = item_group

    byid = {str(o['salesorder_id']): o for o in recent}
    F = defaultdict(lambda: [0, 0, 0, 0, 0, 0, 0, 0]); CR = defaultdict(lambda: [0, 0]); CU = defaultdict(lambda: [0, 0]); T = defaultdict(lambda: [0, 0]); ITEM = {}
    for k, d in det.items():
        o = byid.get(k)
        if not o: continue
        day = wib(o['transaction_date']).date().isoformat(); b = brand(o.get('store_name')); c = chan(o.get('channel_name'))
        f = F[(day, b, c)]
        if is_bad(o):
            f[6] += 1; f[7] += d['sub']
            CR[(b, c, o.get('internal_status'), str(d.get('cr') or o.get('cancel_reason') or 'Tidak disebut')[:60])][0] += 1
            CR[(b, c, o.get('internal_status'), str(d.get('cr') or o.get('cancel_reason') or 'Tidak disebut')[:60])][1] += d['sub']
            continue
        gt = float(o.get('grand_total') or d['gt'])
        f[0] += 1; f[1] += d['sub']; f[2] += d['disc']; f[3] += d['fee']; f[4] += d['ship']; f[5] += gt
        if d.get('cust'): CU[(b, c, d['cust'])][0] += 1; CU[(b, c, d['cust'])][1] += gt
        for iid, code, name, qty, amt, cx in d['items']:
            if cx or skip_item(code, name) and not cafe(code, name): continue
            T[(day, code, b)][0] += qty if qty > 0 else (1 if amt > 0 else 0); T[(day, code, b)][1] += amt  # POS lines carry qty 0: count the line
            ITEM.setdefault(code, (clean(name), group(code, name), price.get(iid, 0)))
    write('finance_daily.csv', ['date', 'brand', 'channel', 'orders', 'gross', 'discounts', 'marketplace_fees', 'shipping', 'net', 'canceled_orders', 'canceled_value'], [list(k) + [v[0]] + [round(x) for x in v[1:6]] + [v[6], round(v[7])] for k, v in sorted(F.items())])
    write('cancel_reasons.csv', ['brand', 'channel', 'status', 'reason', 'orders', 'value'], [list(k) + [v[0], round(v[1])] for k, v in sorted(CR.items(), key=lambda kv: -kv[1][0])])
    CA = defaultdict(lambda: [0, 0, 0, 0.0, 0.0])
    for (b, c, _), v in CU.items():
        a = CA[(b, c)]; a[0] += 1; a[3] += v[1]
        if v[0] > 1: a[1] += 1; a[2] += v[0]; a[4] += v[1]
    write('customers_90d.csv', ['brand', 'channel', 'customers', 'repeat_customers', 'repeat_orders', 'revenue', 'repeat_revenue'], [list(k) + [a[0], a[1], a[2], round(a[3]), round(a[4])] for k, a in CA.items()])
    write('titles_daily.csv', ['date', 'item_code', 'brand', 'qty', 'revenue'], [list(k) + [round(v[0], 2), round(v[1])] for k, v in sorted(T.items())])
    write('items.csv', ['item_code', 'item_name', 'group', 'price'], [[c, n, g, round(p)] for c, (n, g, p) in ITEM.items()])
    write('basket_daily.csv', BASKET_HEADER, basket_rows(recent, det))
    rec, locr, tit = cancel_recovery(recent, det)
    write('cancel_recovery.csv', ['brand', 'channel', 'status', 'orders', 'value', 'reordered_orders', 'reordered_value'], rec)
    write('cancel_by_location.csv', ['location', 'channel', 'status', 'orders', 'value', 'reordered_orders', 'reordered_value'], locr)
    write('cancel_titles.csv', ['item_code', 'item_name', 'brand', 'channel', 'canceled_orders', 'canceled_units', 'value'], tit)
    write('store_daily.csv', ['date', 'location', 'orders', 'units', 'lines', 'identified_orders', 'discounted_orders', 'discount_amount', 'revenue'], store_daily(recent, det))

    # ---------------------------------------------------------------- stock
    inv = {p: get(f'/inventory/v2/{p}/').get('data', []) for p in ['need-restock', 'low-stock', 'days-to-dry', 'best-seller', 'dead-stock']}
    ok = lambda x: not skip_item(x.get('item_code'), x.get('item_name'))
    ro = sorted([x for x in inv['days-to-dry'] if ok(x) and x['location_name'] == 'Semua' and float(x['in_days']) <= 21 and float(x['daily_avg']) >= 0.1], key=lambda x: -float(x['daily_avg']))[:80]
    write('stock_runout.csv', ['item_code', 'item_name', 'daily_avg', 'available_qty', 'days_left', 'reorder_by'], [[x['item_code'], clean(x['item_name']), float(x['daily_avg']), float(x['available_qty']), int(float(x['in_days'])), x['repurchase_date']] for x in ro])
    os_ = sorted([x for x in inv['need-restock'] if ok(x)], key=lambda x: float(x['available_qty']))[:60]
    write('stock_oversold.csv', ['item_code', 'item_name', 'location', 'on_hand', 'reserved', 'available'], [[x['item_code'], clean(x['item_name']), x['location_name'], float(x['end_qty']), float(x['order_qty']), float(x['available_qty'])] for x in os_])
    bs = {(x['item_id'], x['location_name']): float(x['qty']) for x in inv['best-seller'] if ok(x)}
    ls = [x for x in inv['low-stock'] if ok(x)]
    lsl = defaultdict(int)
    for x in ls: lsl[x['location_name']] += 1
    write('stock_low_by_location.csv', ['location', 'low_stock_items'], sorted(lsl.items(), key=lambda kv: -kv[1]))
    lss = sorted([dict(x, sold=bs.get((x['item_id'], x['location_name']), 0)) for x in ls], key=lambda x: -x['sold'])
    write('stock_low_selling.csv', ['item_code', 'item_name', 'location', 'available_qty', 'reorder_point', 'units_sold'], [[x['item_code'], clean(x['item_name']), x['location_name'], float(x['available_qty']), float(x['rop'] or 0), x['sold']] for x in lss if x['sold'] > 0][:60])
    agg = {}
    for x in inv['best-seller']:
        if not ok(x): continue
        a = agg.setdefault(x['item_id'], [x['item_code'], clean(x['item_name']), 0, 0, 0]); a[2] += float(x['qty']); a[3] += float(x['available_qty']); a[4] += 1
    write('stock_best_sellers.csv', ['item_code', 'item_name', 'units_sold', 'available_qty', 'locations'], sorted(agg.values(), key=lambda a: -a[2])[:40])
    ds = [x for x in inv['dead-stock'] if ok(x) and float(x['available_qty']) > 0]
    dead = [x for x in ds if x['last_transaction_sort_key'] >= 90]
    dsl = defaultdict(lambda: [0, 0])
    for x in dead: dsl[x['location_name']][0] += 1; dsl[x['location_name']][1] += float(x['available_qty'])
    write('stock_dead_by_location.csv', ['location', 'items', 'units'], [[k, v[0], round(v[1])] for k, v in sorted(dsl.items(), key=lambda kv: -kv[1][1])])
    write('stock_dead_items.csv', ['item_code', 'item_name', 'location', 'available_qty', 'days_since_sale'], [[x['item_code'], clean(x['item_name']), x['location_name'], float(x['available_qty']), x['last_transaction_sort_key']] for x in sorted(dead, key=lambda x: -float(x['available_qty']))[:50]])
    sold_any = {x['item_id'] for x in inv['best-seller'] if float(x['qty']) > 0}
    tg = {}
    for x in ds:
        a = tg.setdefault(x['item_id'], {'code': x['item_code'], 'name': clean(x['item_name']), 'units': 0, 'locs': [], 'min': 10 ** 9})
        a['units'] += float(x['available_qty']); a['locs'].append(x['location_name']); a['min'] = min(a['min'], x['last_transaction_sort_key'])
    dt = [a for i, a in tg.items() if a['min'] >= 90 and i not in sold_any]
    write('stock_dead_titles.csv', ['item_code', 'item_name', 'units', 'locations', 'location_names', 'days_since_last_sale'], [[a['code'], a['name'], round(a['units']), len(a['locs']), ' / '.join(a['locs']), a['min']] for a in sorted(dt, key=lambda a: (-a['units'], -a['min']))[:60]])
    write('stock_dead_titles_total.csv', ['dead_titles', 'dead_title_units'], [[len(dt), round(sum(a['units'] for a in dt))]])
    # per-location situation + transfers
    L = {}
    def line(x):
        return L.setdefault((x['item_id'], x['location_name']), {'id': x['item_id'], 'code': x['item_code'], 'name': clean(x['item_name']), 'loc': x['location_name'], 'avail': None, 'days': None, 'low': False, 'sold': 0, 'over': False})
    for x in inv['dead-stock']:
        if ok(x): l = line(x); l['avail'] = float(x['available_qty']); l['days'] = x['last_transaction_sort_key']
    for x in inv['low-stock']:
        if ok(x): l = line(x); l['avail'] = l['avail'] if l['avail'] is not None else float(x['available_qty']); l['low'] = True
    for x in inv['best-seller']:
        if ok(x): l = line(x); l['avail'] = l['avail'] if l['avail'] is not None else float(x['available_qty']); l['sold'] = float(x['qty'])
    for x in inv['need-restock']:
        if ok(x): l = line(x); l['avail'] = float(x['available_qty']); l['over'] = True
    S = defaultdict(lambda: [0] * 14)
    for l in L.values():
        if l['loc'] == 'Semua': continue
        s = S[l['loc']]; u = max(0, l['avail'] or 0); p = price.get(l['id'], 0)
        if u > 0:
            s[0] += 1; s[1] += u; s[2] += u * p
            d = l['days']
            s[9 if d is None or d < 30 else 10 if d < 90 else 11 if d < 180 else 12] += u
            if d is not None and d >= 90: s[6] += 1; s[7] += u; s[8] += u * p
            if l['low']: s[3] += 1
        if l['over'] or (l['avail'] or 0) < 0: s[4] += 1; s[5] += -min(0, l['avail'] or 0)
        s[13] += l['sold']
    write('stock_locations.csv', ['location', 'sku_lines', 'units', 'retail_value', 'low_lines', 'oversold_lines', 'oversold_units', 'dead_lines', 'dead_units', 'dead_value', 'units_age_0_29', 'units_age_30_89', 'units_age_90_179', 'units_age_180_plus', 'units_sold'],
          [[k] + [round(x) for x in v] for k, v in sorted(S.items(), key=lambda kv: -kv[1][2])])
    by = defaultdict(list)
    for l in L.values():
        if l['loc'] != 'Semua': by[l['id']].append(l)
    TR = []
    for ls_ in by.values():
        for s in [l for l in ls_ if (l['days'] or 0) >= 90 and (l['avail'] or 0) >= 2]:
            for d in [l for l in ls_ if l['sold'] >= 3 and (l['avail'] or 0) < l['sold']]:
                if d['loc'] == s['loc']: continue
                q = min(s['avail'], max(1, round(d['sold'] - (d['avail'] or 0))))
                TR.append([s['code'], s['name'], s['loc'], round(s['avail']), s['days'], d['loc'], round(d['sold']), round(d['avail'] or 0), q, round(q * price.get(s['id'], 0))])
    TR.sort(key=lambda r: -r[9]); seen = set(); TR2 = []
    for r in TR:
        if (r[0], r[2]) in seen: continue
        seen.add((r[0], r[2])); TR2.append(r)
    write('stock_transfers.csv', ['item_code', 'item_name', 'from_location', 'from_units', 'days_since_sale_from', 'to_location', 'to_units_sold', 'to_available', 'suggested_qty', 'suggested_value'], TR2[:60])
    last = max(o['transaction_date'] for o in orders)
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    write('snapshots.csv', ['source', 'updated_at', 'last_order_at'], [['sales', stamp, last], ['stock', stamp, ''], ['sales_detail_90d', stamp, '']])

    # ---------------------------------------------------------------- transfer workbook (store format)
    try:
        transfer_workbook(recent, det, price, master, bundles, now)
    except Exception as e:  # never let the workbook break the data sync
        import traceback; traceback.print_exc()
        print('transfer workbook skipped:', e, file=sys.stderr)
    try:
        scout_picks()
    except Exception as e:
        print('scout picks skipped:', e, file=sys.stderr)
    try:
        alerts_from_data(now)
    except Exception as e:
        import traceback; traceback.print_exc()
        print('alerts skipped:', e, file=sys.stderr)


def all_stocks(ids):
    """POST /inventory/items/all-stocks/ in chunks -> (stock[(item_id, location_name)] = (on_hand, reserved, available), brands[item_id])."""
    stock, brands, locname, onorder = {}, {}, {}, defaultdict(float)
    ids = list(ids)
    for i in range(0, len(ids), 200):  # Jubelio caps ids at 200 per call
        r = http('POST', BASE + '/inventory/items/all-stocks/', {'ids': ids[i:i + 200]}, token=TOKEN)
        for l in r.get('locations') or []:
            if l.get('location_name'): locname[str(l.get('location_id'))] = l['location_name'].strip()
        for it in r.get('data') or []:
            iid = it.get('item_id')
            if it.get('brand_name'): brands[iid] = it['brand_name']
            for ls in it.get('location_stocks') or []:
                loc = locname.get(str(ls.get('location_id'))) or (ls.get('location_name') or ls.get('location_code') or '').strip()
                if not loc: continue
                oh = float(ls.get('on_hand') or 0); rs = float(ls.get('reserved') or 0)
                av = float(ls['available']) if ls.get('available') is not None else oh - rs
                stock[(iid, loc)] = (oh, rs, av)
                onorder[iid] += float(ls.get('on_order') or 0)
    return stock, brands, onorder


def transfer_workbook(recent, det, price, master, bundles, now):
    import transfer_workbook as tw
    asof = now.date(); end = asof - timedelta(days=1); start = asof - timedelta(days=92)
    months = tw.month_labels(start, end)
    pos, online, last, names = defaultdict(dict), defaultdict(float), {}, dict(master)
    stores = set()
    for o in recent:
        if is_bad(o): continue
        d = det.get(str(o['salesorder_id']))
        if not d: continue
        day = wib(o['transaction_date']).date()
        if day < start or day > end: continue
        is_pos = chan(o.get('channel_name')) == 'In-store POS'; loc = (o.get('location_name') or '').strip()
        if is_pos and not tw.is_store_loc(loc): continue
        if is_pos: stores.add(loc)
        for iid, code, name, qty, amt, cx in d['items']:
            if cx or skip_item(code, name) or amt <= 0: continue
            u = qty if qty > 0 else 1
            names.setdefault(iid, (code or '', clean(name)))
            if is_pos:
                m = day.strftime('%Y-%m'); pos[(loc, iid)][m] = pos[(loc, iid)].get(m, 0) + u
                last[(loc, iid)] = max(last.get((loc, iid), day), day)
            else:
                online[iid] += u
    stores = sorted(stores)
    ids = set(price) | {iid for (_, iid) in pos} | set(online)
    stock, brands, onorder = all_stocks(ids)
    print('all-stocks', len(ids), 'items,', len({l for _, l in stock}), 'locations, stores', stores)
    out = os.path.join(OUT, 'transfer_stok_toko_offline.xlsx')
    res = tw.build(out, stores, months, pos, online, last, stock, names, brands, bundles, start, end, asof)
    print('wrote transfer_stok_toko_offline.xlsx', res['transfer_rows'], 'transfers,', res['restock_rows'], 'restock')
    write('transfer_summary.csv', ['store', 'sku_out_sold', 'sku_out_sold2', 'sku_transfer', 'sku_full', 'sku_high', 'qty_transfer', 'sku_restock', 'window_start', 'window_end', 'generated_at'],
          [[st] + [p['sold1'], p['sold2'], p['transfer'], p['full'], p['high'], p['qty'], p['restock']] + [start.isoformat(), end.isoformat(), now.strftime('%Y-%m-%dT%H:%M:%S+07:00')] for st, p in sorted(res['stores'].items())])
    try:
        buy_list_feed(recent, det, stock, onorder, names, price, now, tw.is_store_loc)
    except Exception as e:
        import traceback; traceback.print_exc()
        print('buy list skipped:', e, file=sys.stderr)


def buy_list_feed(recent, det, stock, onorder, names, price, now, is_store_loc):
    import buy_list
    asof = now.date(); since = asof - timedelta(days=90)
    sales = {}
    for o in recent:
        if is_bad(o): continue
        d = det.get(str(o['salesorder_id']))
        if not d: continue
        day = wib(o['transaction_date']).date()
        if day < since: continue
        for iid, code, name, qty, amt, cx in d['items']:
            if cx or skip_item(code, name) or amt <= 0: continue
            a = sales.setdefault(iid, {'u': 0.0, 'v': 0.0, 'last': day})
            a['u'] += qty if qty > 0 else 1; a['v'] += amt
            if day > a['last']: a['last'] = day
            names.setdefault(iid, (code or '', clean(name)))
    groups = {iid: item_group(c, n) for iid, (c, n) in names.items()}
    try:
        supplier_of, last_po, lead_by, po_count = purchases()
    except Exception as e:
        print('purchase orders unavailable, suppliers left blank:', e, file=sys.stderr)
        supplier_of, last_po, lead_by, po_count = {}, {}, {}, {}
    sellable = lambda loc: loc == 'ONLINE' or is_store_loc(loc)
    res = buy_list.build(OUT, asof, sales, stock, onorder, names, groups, price, supplier_of, last_po, lead_by, po_count, sellable)
    print('buy list', res)


if __name__ == '__main__':
    main()
