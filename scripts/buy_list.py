"""Data half of the weekly buy list, published daily by the sync for the dashboard and for Booky Scout.

Writes to data/:
  reorder.csv      titles that will run out before a reorder lands (lead time per supplier, else 60-90 days)
  slow_movers.csv  stock that is not selling: candidates to return, transfer or mark down
  suppliers.csv    performance per supplier (from Jubelio purchase orders)
  catalog.csv      everything we carry or sold in 90 days, with stock by location
  daftar_beli_data.pdf  the same lists as an Indonesian A4 report
Buy prices from purchase orders are never written out: the repo and site are public.
"""
import csv, math, os, statistics
from collections import defaultdict
from datetime import date, timedelta

DEFAULT_LEAD = 90          # days, upper end of the 60-90 assumption when a supplier has no measured lead time
SELL_AFTER_ARRIVAL = 30    # suggested quantity covers the lead time plus this many days of selling
MIN_UNITS_90D = 6          # only titles selling at least this many units in 90 days go on the reorder list


def _w(out, name, header, rows):
    with open(os.path.join(out, name), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(header); w.writerows(rows)
    print('wrote', name, len(rows))


def build(out, asof, sales, stock, onorder, names, groups, price, supplier_of, last_po, lead_by_supplier, po_count, is_sellable):
    """sales[iid] = dict(u=units_90d, v=revenue_90d, last=date); stock[(iid, loc)] = (on_hand, reserved, available);
    onorder[iid] = units on order; names[iid] = (code, name); groups[iid] = group label; price[iid] = retail price;
    supplier_of[iid] = supplier name; last_po[iid] = date of last PO line; lead_by_supplier[s] = (median_days, samples)."""
    avail = defaultdict(float); byloc = defaultdict(list)
    for (iid, loc), (oh, rs, av) in stock.items():
        if not is_sellable(loc) or av <= 0: continue
        avail[iid] += av; byloc[iid].append((loc, av))
    loc_str = lambda iid: '; '.join(f'{l} {int(a) if a == int(a) else a}' for l, a in sorted(byloc.get(iid, []), key=lambda x: -x[1]))
    items = set(sales) | {i for i, a in avail.items() if a > 0}

    # ---- reorder
    reorder = []
    for iid in items:
        s = sales.get(iid)
        if not s or s['u'] < MIN_UNITS_90D: continue
        if groups.get(iid) == 'Kafe': continue
        avg = s['u'] / 90.0; av = avail.get(iid, 0.0); oo = onorder.get(iid, 0.0)
        sup = supplier_of.get(iid, '')
        lead, n = lead_by_supplier.get(sup, (None, 0))
        L = lead if (lead and n >= 2) else DEFAULT_LEAD
        cover = (av + oo) / avg if avg else 9999
        if cover >= L + SELL_AFTER_ARRIVAL: continue
        urg = 'KRITIS' if cover < 60 else 'SEGERA' if cover < L else 'PANTAU'
        qty = max(0, math.ceil(avg * (L + SELL_AFTER_ARRIVAL) - av - oo))
        code, name = names.get(iid, ('', ''))
        reorder.append([code, name, groups.get(iid, ''), sup or '', round(avg, 2), int(s['u']), int(av), int(oo), round(cover), L, 'diukur' if (lead and n >= 2) else 'asumsi',
                        qty, urg, s['last'].isoformat() if s.get('last') else '', last_po.get(iid, ''), loc_str(iid), round(price.get(iid, 0))])
    rank = {'KRITIS': 0, 'SEGERA': 1, 'PANTAU': 2}
    reorder.sort(key=lambda r: (rank[r[12]], r[8], -r[5]))
    _w(out, 'reorder.csv', ['item_code', 'item_name', 'group', 'supplier', 'daily_avg_90d', 'units_90d', 'available', 'on_order', 'days_cover',
                           'lead_days', 'lead_source', 'suggested_qty', 'urgency', 'last_sale', 'last_po', 'available_by_location', 'price'], reorder)

    # ---- slow movers
    slow = []
    for iid, av in avail.items():
        if av < 3 or groups.get(iid) == 'Kafe': continue
        s = sales.get(iid); u = s['u'] if s else 0
        if u == 0: why = 'Tidak laku 90 hari'
        elif u <= 2 and av >= 15: why = 'Sangat lambat (≤2 unit/90 hari, stok ≥15)'
        else: continue
        code, name = names.get(iid, ('', ''))
        slow.append([code, name, groups.get(iid, ''), supplier_of.get(iid, ''), int(av), int(u), round(av * price.get(iid, 0)), why, s['last'].isoformat() if s and s.get('last') else '>90 hari', last_po.get(iid, ''), loc_str(iid)])
    slow.sort(key=lambda r: -r[6])
    _w(out, 'slow_movers.csv', ['item_code', 'item_name', 'group', 'supplier', 'available', 'units_90d', 'retail_value', 'reason', 'last_sale', 'last_po', 'available_by_location'], slow[:400])

    # ---- suppliers
    S = defaultdict(lambda: dict(ts=0, us=0, vs=0.0, tsold=0, u=0, v=0.0, slowu=0, slowv=0.0, kr=0, sg=0, lastpo=''))
    for iid in items:
        sup = supplier_of.get(iid) or '(tanpa PO di Jubelio)'
        if groups.get(iid) == 'Kafe': continue
        a = S[sup]; av = avail.get(iid, 0.0); s = sales.get(iid)
        if av > 0: a['ts'] += 1; a['us'] += av; a['vs'] += av * price.get(iid, 0)
        if s and s['u'] > 0: a['tsold'] += 1; a['u'] += s['u']; a['v'] += s['v']
        if av >= 3 and (not s or s['u'] == 0): a['slowu'] += av; a['slowv'] += av * price.get(iid, 0)
        if last_po.get(iid, '') > a['lastpo']: a['lastpo'] = last_po[iid]
    for r in reorder:
        sup = r[3] or '(tanpa PO di Jubelio)'
        if r[12] == 'KRITIS': S[sup]['kr'] += 1
        elif r[12] == 'SEGERA': S[sup]['sg'] += 1
    sup_rows = []
    for sup, a in S.items():
        if not a['ts'] and not a['tsold']: continue
        lead, n = lead_by_supplier.get(sup, (None, 0))
        st = a['u'] / (a['u'] + a['us']) if (a['u'] + a['us']) else None
        sup_rows.append([sup, a['ts'], int(a['us']), round(a['vs']), a['tsold'], int(a['u']), round(a['v']), round(st, 4) if st is not None else '',
                         int(a['slowu']), round(a['slowv']), a['kr'], a['sg'], lead if lead is not None else '', n, a['lastpo'], po_count.get(sup, 0)])
    sup_rows.sort(key=lambda r: -r[6])
    _w(out, 'suppliers.csv', ['supplier', 'titles_in_stock', 'units_in_stock', 'stock_value_retail', 'titles_sold_90d', 'units_90d', 'revenue_90d', 'sell_through_90d',
                             'slow_units', 'slow_value_retail', 'reorder_kritis', 'reorder_segera', 'lead_days_median', 'lead_samples', 'last_po', 'pos_12m'], sup_rows)

    # ---- catalogue
    cat = []
    for iid in items:
        if groups.get(iid) == 'Kafe': continue
        code, name = names.get(iid, ('', ''))
        if not code: continue
        s = sales.get(iid)
        cat.append([code, name, groups.get(iid, ''), supplier_of.get(iid, ''), round(price.get(iid, 0)), int(avail.get(iid, 0)), loc_str(iid), int(onorder.get(iid, 0)),
                    int(s['u']) if s else 0, s['last'].isoformat() if s and s.get('last') else ''])
    cat.sort(key=lambda r: (-r[8], -r[5]))
    _w(out, 'catalog.csv', ['item_code', 'item_name', 'group', 'supplier', 'price', 'available', 'available_by_location', 'on_order', 'units_90d', 'last_sale'], cat)

    pdf(os.path.join(out, 'daftar_beli_data.pdf'), asof, reorder, slow, sup_rows)
    return dict(reorder=len(reorder), kritis=sum(1 for r in reorder if r[12] == 'KRITIS'), slow=len(slow), suppliers=len(sup_rows), catalog=len(cat))


def pdf(path, asof, reorder, slow, sup_rows):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    GREEN = colors.HexColor('#0F2D24'); CREAM = colors.HexColor('#F3EFE6'); LINE = colors.HexColor('#D9D2C2'); RED = colors.HexColor('#B8362A'); WOOD = colors.HexColor('#8A5600')
    H1 = ParagraphStyle('h1', fontName='Helvetica-Bold', fontSize=16, leading=20, textColor=GREEN, spaceAfter=2)
    H2 = ParagraphStyle('h2', fontName='Helvetica-Bold', fontSize=11.5, textColor=GREEN, spaceBefore=10, spaceAfter=4)
    P = ParagraphStyle('p', fontName='Helvetica', fontSize=9, leading=12.5)
    SM = ParagraphStyle('sm', fontName='Helvetica', fontSize=7.5, leading=10, textColor=colors.HexColor('#5C6660'))
    CELL = ParagraphStyle('c', fontName='Helvetica', fontSize=7.5, leading=9)
    MON = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des']
    d = f'{asof.day} {MON[asof.month - 1]} {asof.year}'
    rp = lambda v: 'Rp ' + ((f'{v/1e9:.1f} M' if v >= 1e9 else f'{v/1e6:.1f} jt' if v >= 1e6 else f'{v/1e3:.0f} rb').replace('.', ','))

    def tbl(head, rows, widths, urg_col=None):
        data = [head] + rows
        t = Table([[Paragraph(str(c), CELL) for c in r] for r in data], colWidths=widths, repeatRows=1)
        st = [('BACKGROUND', (0, 0), (-1, 0), GREEN), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white), ('LINEBELOW', (0, 0), (-1, -1), 0.4, LINE),
              ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 3), ('RIGHTPADDING', (0, 0), (-1, -1), 3), ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]
        for i in range(1, len(data)):
            if i % 2 == 0: st.append(('BACKGROUND', (0, i), (-1, i), CREAM))
        t.setStyle(TableStyle(st))
        for i in range(1, len(data)):  # header row text white
            pass
        return t

    kr = [r for r in reorder if r[12] == 'KRITIS']; sg = [r for r in reorder if r[12] == 'SEGERA']; pv = [r for r in reorder if r[12] == 'PANTAU']
    slow_val = sum(r[6] for r in slow)
    top = ', '.join(r[1][:40] for r in kr[:3])
    tldr = (f'{len(kr)} judul akan habis sebelum pesanan ulang bisa tiba (KRITIS) dan {len(sg)} judul perlu dipesan minggu ini (SEGERA), '
            f'berdasarkan kecepatan jual 90 hari dan stok tersedia di toko serta gudang online. '
            + (f'Paling mendesak: {top}. ' if top else '')
            + f'{len(slow)} judul tidak laku atau sangat lambat, senilai {rp(slow_val)} (harga jual): kandidat retur, transfer atau diskon. '
            'Lead time diukur dari pesanan pembelian di Jubelio bila ada; selain itu diasumsikan 90 hari. Harga pokok tidak dicantumkan.')
    hdr_head = lambda h: [Paragraph(f'<font color="white"><b>{x}</b></font>', CELL) for x in h]

    story = [Paragraph('Daftar Beli – Data Toko', H1), Paragraph(f'Wonder Bookstore &amp; Sinar Starbooks · {d} · sumber: Jubelio (dashboard, sinkron harian)', SM), Spacer(1, 6),
             Paragraph('<b>Ringkasan.</b> ' + tldr, P)]

    def section(title, rows, limit):
        story.append(Paragraph(f'{title} ({len(rows)} judul)', H2))
        if not rows: story.append(Paragraph('Tidak ada.', P)); return
        head = ['Judul', 'Pemasok', 'Laku per hari', 'Tersedia', 'Dipesan', 'Cukup (hari)', 'Lead time', 'Saran pesan', 'ISBN / kode']
        body = [[r[1][:70], r[3] or '–', f'{r[4]:.2f}'.replace('.', ','), r[6], r[7], r[8], f"{r[9]} hr ({r[10]})", r[11], r[0]] for r in rows[:limit]]
        t = Table([hdr_head(head)] + [[Paragraph(str(c), CELL) for c in row] for row in body], colWidths=[46*mm, 28*mm, 15*mm, 15*mm, 14*mm, 13*mm, 18*mm, 14*mm, 23*mm], repeatRows=1)
        st = [('BACKGROUND', (0, 0), (-1, 0), GREEN), ('LINEBELOW', (0, 0), (-1, -1), 0.4, LINE), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 3), ('RIGHTPADDING', (0, 0), (-1, -1), 3),
              ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]
        st += [('BACKGROUND', (0, i), (-1, i), CREAM) for i in range(2, len(body) + 1, 2)]
        t.setStyle(TableStyle(st)); story.append(t)
        if len(rows) > limit: story.append(Paragraph(f'… dan {len(rows) - limit} judul lain di reorder.csv / dashboard tab Stok.', SM))

    section('KRITIS: habis sebelum pesanan ulang tiba', kr, 40)
    section('SEGERA: pesan minggu ini', sg, 40)
    section('PANTAU: pesan bulan ini', pv, 20)

    story.append(Paragraph(f'Lambat laku: retur, transfer atau diskon ({len(slow)} judul, {rp(slow_val)} harga jual)', H2))
    head = ['Judul', 'Pemasok', 'Stok', 'Laku 90 hr', 'Nilai jual', 'Alasan', 'Lokasi']
    body = [[r[1][:60], r[3] or '–', r[4], r[5], rp(r[6]), r[7], r[10][:60]] for r in slow[:30]]
    t = Table([hdr_head(head)] + [[Paragraph(str(c), CELL) for c in row] for row in body], colWidths=[50*mm, 26*mm, 11*mm, 13*mm, 18*mm, 28*mm, 38*mm], repeatRows=1)
    t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), GREEN), ('LINEBELOW', (0, 0), (-1, -1), 0.4, LINE), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 3), ('RIGHTPADDING', (0, 0), (-1, -1), 3)] + [('BACKGROUND', (0, i), (-1, i), CREAM) for i in range(2, len(body) + 1, 2)]))
    story.append(t)

    story.append(Paragraph('Pemasok teratas (90 hari)', H2))
    head = ['Pemasok', 'Judul laku', 'Unit 90 hr', 'Penjualan', 'Sell-through', 'Stok lambat', 'KRITIS', 'Lead time']
    body = [[r[0], r[4], r[5], rp(r[6]), (f'{r[7]*100:.0f}%' if r[7] != '' else '–'), rp(r[9]), r[10], (f'{r[12]} hr ({r[13]} PO)' if r[12] != '' else 'belum terukur')] for r in sup_rows[:20]]
    t = Table([hdr_head(head)] + [[Paragraph(str(c), CELL) for c in row] for row in body], colWidths=[46*mm, 16*mm, 16*mm, 20*mm, 18*mm, 20*mm, 13*mm, 25*mm], repeatRows=1)
    t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), GREEN), ('LINEBELOW', (0, 0), (-1, -1), 0.4, LINE), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 3), ('RIGHTPADDING', (0, 0), (-1, -1), 3)] + [('BACKGROUND', (0, i), (-1, i), CREAM) for i in range(2, len(body) + 1, 2)]))
    story.append(t)

    story += [Spacer(1, 8), Paragraph('<b>Cara baca.</b> Laku/hari = unit terjual 90 hari terakhir ÷ 90 (semua kanal; baris kasir tanpa qty dihitung 1). Tersedia = stok tersedia di toko dan gudang online (pameran tidak dihitung). '
             'Cukup (hari) = (tersedia + dipesan) ÷ laku/hari. KRITIS = cukup kurang dari 60 hari; SEGERA = cukup kurang dari lead time; PANTAU = kurang dari lead time + 30 hari. '
             'Saran pesan = kebutuhan selama lead time + 30 hari, dikurangi stok tersedia dan yang sudah dipesan. Lead time "diukur" = median jarak tanggal PO ke tanggal tagihan pembelian di Jubelio (minimal 2 PO); "asumsi" = 90 hari. '
             'Pemasok = pemasok PO terakhir untuk barang itu di Jubelio. Harga pokok dan syarat kontrak tidak dicantumkan.', SM)]
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=12*mm, rightMargin=12*mm, topMargin=12*mm, bottomMargin=12*mm, title=f'Daftar Beli – Data Toko {d}', author='Dashboard Penjualan & Stok')
    doc.build(story)
    print('wrote', os.path.basename(path))
