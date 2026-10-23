"""Builds Transfer_Stok_Toko_Offline.xlsx: the stock-transfer workbook the stores use.

Same four sheets and rules as the team's manual file:
  1. Ringkasan                      per-store counts, transfer routes, how to read
  2. Rekomendasi Transfer           out of stock at a store but selling there; up to 3 sources
  3. Daftar Transfer per Rute       the same transfers listed per source -> destination
  4. Perlu Restock (Tanpa Sumber)   selling (>=2) but no store has surplus

Rules: suggested qty = ceil(3-month POS sales / 2), min 1 (about 1.5 months of cover).
Source surplus = available - ceil(its own 3-month sales / 2); a store that doesn't sell the
title may give all of it. Sources are tried in order: same-region stores, then Gudang ONLINE
(keeps half its 3-month online sales), then other-region stores; destinations with higher
sales are served first. Bundles, packaging, café items and Pameran/Sample/Transit locations
are excluded.
"""
import math
from collections import defaultdict
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ONLINE = 'ONLINE'
ONLINE_LABEL = 'Gudang ONLINE'
THIN = Side(style='thin', color='FFBFBFBF')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
F_TITLE = Font(bold=True, size=16, color='FF1F3864')
F_SUB = Font(italic=True, color='FF595959')
F_SUB_SM = Font(italic=True, size=10, color='FF595959')
F_H2 = Font(bold=True, size=12, color='FF1F3864')
F_H1 = Font(bold=True, size=14, color='FF1F3864')
F_HEAD = Font(bold=True, color='FFFFFFFF')
F_BOLD = Font(bold=True)
FILL_HEAD = PatternFill('solid', fgColor='FF2F5597')
FILL_HEAD_DARK = PatternFill('solid', fgColor='FF1F3864')
FILL_HEAD_GREEN = PatternFill('solid', fgColor='FF548235')
FILL_TOTAL = PatternFill('solid', fgColor='FFD9E2F3')
FILL_OK = PatternFill('solid', fgColor='FFC6EFCE')      # Penuh
FILL_PART = PatternFill('solid', fgColor='FFFFEB9C')    # Sebagian
FILL_HIGH = PatternFill('solid', fgColor='FFF8CBAD')    # Prioritas tinggi
FILL_MED = PatternFill('solid', fgColor='FFFFE699')     # Prioritas sedang
CENTER = Alignment(horizontal='center', vertical='center', wrap_text=True)
CENTER1 = Alignment(horizontal='center')
TOPWRAP = Alignment(vertical='top', wrap_text=True)


def is_store_loc(name):
    n = (name or '').upper()
    return bool(n) and n != ONLINE and not n.startswith(('PAMERAN', 'SAMPLE', 'TRANSIT'))


def region_of(store):
    return 'Bali' if store.upper().startswith('BALI') else 'Jakarta'


def half(n):
    return max(1, math.ceil(n / 2)) if n > 0 else 0


def priority(sold, recent30):
    if sold >= 6 or (sold >= 3 and recent30): return 'Tinggi'
    if sold >= 3 or (sold == 2 and recent30): return 'Sedang'
    return 'Rendah'


def month_labels(start, end):
    """[('2026-07', 'Jul (23–31)'), ('2026-08', 'Agu'), ...] for the window start..end."""
    MON = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des']
    out = []; y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        key = f'{y}-{m:02d}'; lab = MON[m - 1]
        first = start if (y, m) == (start.year, start.month) else None
        last = end if (y, m) == (end.year, end.month) else None
        if first and first.day != 1 and last: lab += f' ({first.day}–{last.day})'
        elif first and first.day != 1: lab += f' ({first.day}–{(date(y + (m == 12), m % 12 + 1, 1) - date.resolution).day})'
        elif last and last.day != (date(y + (m == 12), m % 12 + 1, 1) - date.resolution).day: lab += f' (1–{last.day})'
        out.append((key, lab)); y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def plan(stores, months, pos_sales, online_sales, last_sale, stock, names, brands, bundles, asof):
    """Returns (rec_rows, route_rows, restock_rows, per_store, notes) as plain dicts."""
    keys = [k for k, _ in months]
    recent_cut = asof.fromordinal(asof.toordinal() - 30)
    stock_of = lambda iid, loc: stock.get((iid, loc), (0.0, 0.0, 0.0))
    pos_total = lambda loc, iid: sum(pos_sales.get((loc, iid), {}).values())

    # candidates: sold at the store in the window, available <= 0 there
    cand = []
    for (store, iid), bym in pos_sales.items():
        if store not in stores or iid in bundles: continue
        sold = sum(bym.values())
        if sold < 1: continue
        oh, rs, av = stock_of(iid, store)
        if av > 0: continue
        cand.append((store, iid, sold, oh, av))
    cand.sort(key=lambda c: (-c[2], c[0], names.get(c[1], ('', ''))[1]))

    surplus = {}
    def surplus_of(iid, loc):
        k = (iid, loc)
        if k not in surplus:
            oh, rs, av = stock_of(iid, loc)
            keep = half(online_sales.get(iid, 0)) if loc == ONLINE else half(pos_total(loc, iid))
            surplus[k] = max(0.0, av - keep)
        return surplus[k]

    rec, routes, restock = [], [], []
    per_store = {s: dict(sold1=0, sold2=0, transfer=0, full=0, high=0, qty=0, restock=0) for s in stores}
    for store, iid, sold, oh, av in cand:
        ps = per_store[store]; ps['sold1'] += 1
        if sold >= 2: ps['sold2'] += 1
        need = half(sold)
        same = [s for s in stores if s != store and region_of(s) == region_of(store)]
        other = [s for s in stores if s != store and region_of(s) != region_of(store)]
        tiers = [same, [ONLINE], other]
        srcs, left = [], need
        for tier in tiers:
            if left <= 0 or len(srcs) >= 3: break
            for loc in sorted(tier, key=lambda l: -surplus_of(iid, l)):
                if left <= 0 or len(srcs) >= 3: break
                sp = surplus_of(iid, loc)
                if sp <= 0: continue
                q = min(sp, left); q = int(q) if q == int(q) else round(q, 1)
                if q <= 0: continue
                surplus[(iid, loc)] = sp - q; left -= q
                srcs.append((loc, stock_of(iid, loc)[2], q))
        bym = pos_sales.get((store, iid), {})
        ls = last_sale.get((store, iid)); pr = priority(sold, bool(ls and ls >= recent_cut))
        code, name = names.get(iid, ('', ''))
        note = f'Tercatat {int(oh)} pcs tapi sudah teralokasi ke pesanan – cek fisik' if oh > 0 else ''
        if srcs:
            total = sum(q for _, _, q in srcs); short = max(0, need - total)
            status = 'Penuh' if short == 0 else 'Sebagian'
            ps['transfer'] += 1; ps['qty'] += total
            if status == 'Penuh': ps['full'] += 1
            if pr == 'Tinggi': ps['high'] += 1
            row = [store, code, name, brands.get(iid, '') or ''] + [bym.get(k, 0) for k in keys] + [sold, ls, av, need]
            for i in range(3):
                row += [ONLINE_LABEL if srcs[i][0] == ONLINE else srcs[i][0], srcs[i][1], srcs[i][2]] if i < len(srcs) else ['', '', '']
            row += [total, short, status, pr, 0, note]
            rec.append(row)
            for loc, sav, q in srcs:
                src_sold = online_sales.get(iid, 0) if loc == ONLINE else pos_total(loc, iid)
                routes.append([ONLINE_LABEL if loc == ONLINE else loc, store, code, name, q, sav, src_sold, sold, pr])
        elif sold >= 2:
            ps['restock'] += 1
            pam = sum(v[2] for (i2, loc), v in stock.items() if i2 == iid and loc.upper().startswith('PAMERAN') and v[2] > 0)
            restock.append([store, code, name, brands.get(iid, '') or ''] + [bym.get(k, 0) for k in keys] + [sold, ls, need, pam, pr])
    routes.sort(key=lambda r: (r[0], r[1], r[3]))
    return rec, routes, restock, per_store


def _head(ws, r, labels, fill=FILL_HEAD, height=45):
    for c, lab in enumerate(labels, 1):
        x = ws.cell(row=r, column=c, value=lab); x.font = F_HEAD; x.fill = fill; x.border = BORDER; x.alignment = CENTER
    ws.row_dimensions[r].height = height


def _row(ws, r, vals, date_cols=(), center_from=1):
    for c, v in enumerate(vals, 1):
        x = ws.cell(row=r, column=c, value=v); x.border = BORDER
        if c in date_cols and v: x.number_format = 'dd/mm/yyyy'
        if c >= center_from: x.alignment = CENTER1


def _widths(ws, widths):
    for i, w in enumerate(widths, 1):
        if w: ws.column_dimensions[get_column_letter(i)].width = w


def build(path, stores, months, pos_sales, online_sales, last_sale, stock, names, brands, bundles, window_start, window_end, asof):
    rec, routes, restock, per_store = plan(stores, months, pos_sales, online_sales, last_sale, stock, names, brands, bundles, asof)
    MONL = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember']
    MON = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des']
    fd = lambda d: f'{d.day} {MON[d.month - 1]}' + (f' {d.year}' if d == window_end else '')
    win = f'{fd(window_start)} – {window_end.day} {MON[window_end.month - 1]} {window_end.year}'
    asof_s = f'{asof.day} {MON[asof.month - 1]} {asof.year}'
    mlabs = [lab for _, lab in months]
    wb = Workbook()

    # ---- 1. Ringkasan
    ws = wb.active; ws.title = 'Ringkasan'
    ws['A1'] = 'Analisa Stok Habis Berpotensi Jual – Toko Offline'; ws['A1'].font = F_TITLE
    ws['A2'] = f'Data penjualan POS {win} (Jubelio) • Posisi stok per {asof_s}'; ws['A2'].font = F_SUB
    _head(ws, 4, ['Toko', 'SKU Habis & Pernah Laku (≥1)', 'SKU Habis & Laku ≥2', 'SKU Bisa Ditransfer', '…di antaranya Terpenuhi Penuh', '…Prioritas Tinggi', 'Total Qty Transfer', 'SKU Perlu Restock (≥2, tanpa sumber)'])
    r = 5; tot = [0] * 7
    for s in sorted(stores):
        p = per_store[s]; vals = [p['sold1'], p['sold2'], p['transfer'], p['full'], p['high'], p['qty'], p['restock']]
        tot = [a + b for a, b in zip(tot, vals)]
        _row(ws, r, [s] + vals, center_from=2); r += 1
    _row(ws, r, ['TOTAL'] + tot, center_from=2)
    for c in range(1, 9): ws.cell(row=r, column=c).font = F_BOLD; ws.cell(row=r, column=c).fill = FILL_TOTAL
    r += 3
    ws.cell(row=r, column=1, value='Rute Transfer (Dari → Ke)').font = F_H2; r += 1
    _head(ws, r, ['Dari', 'Ke', 'Jumlah SKU', 'Total Qty'], height=15); r += 1
    rt = defaultdict(lambda: [0, 0])
    for x in routes: rt[(x[0], x[1])][0] += 1; rt[(x[0], x[1])][1] += x[4]
    for (a, b), (n, q) in sorted(rt.items(), key=lambda kv: -kv[1][1]):
        _row(ws, r, [a, b, n, q], center_from=3); r += 1
    r += 2
    ws.cell(row=r, column=1, value='Cara Baca & Asumsi').font = F_H2; r += 1
    jk = ', '.join(s for s in sorted(stores) if region_of(s) == 'Jakarta'); bl = ', '.join(s for s in sorted(stores) if region_of(s) == 'Bali')
    notes = [
        f'• Toko offline: {", ".join(sorted(stores))} (lokasi Pameran, SAMPLE, Transit tidak dihitung sebagai tujuan/sumber).',
        '• Penjualan per toko diambil dari transaksi JUBELIO-POS (lokasi pesanan = toko). Angka = qty terjual, pesanan batal/retur tidak dihitung.',
        '• "Habis" = Stok Tersedia ≤ 0 di Jubelio (stok fisik tercatat dikurangi qty yang masih teralokasi ke pesanan). Bila masih ada stok tercatat tapi teralokasi, dicatat di kolom Catatan – mohon cek fisik.',
        '• Saran Qty = ½ × penjualan 3 bulan (≈ kebutuhan 1,5 bulan), dibulatkan ke atas, minimal 1.',
        '• Stok lebih di toko sumber = Stok Tersedia − ½ × penjualan 3 bulan toko itu sendiri (toko sumber tetap pegang ±1,5 bulan stok). Toko yang tidak menjual judul tsb boleh transfer seluruh stoknya.',
        '• Kolom "Stok Tersedia di Sumber (sebelum transfer)" = stok tersedia toko sumber saat ini, belum dikurangi transfer apa pun (bila 1 sumber mengirim ke beberapa toko untuk SKU yang sama, angkanya sama di tiap baris).',
        f'• Urutan sumber: toko satu wilayah (Jakarta: {jk} | Bali: {bl}) → Gudang ONLINE (sisakan ½ × penjualan online 3 bln) → toko beda wilayah.',
        '• Bila 1 sumber diminta beberapa toko, yang penjualannya lebih tinggi didahulukan.',
        '• Prioritas: Tinggi = terjual ≥6, atau ≥3 dan masih laku 30 hari terakhir; Sedang = ≥3, atau 2 dan laku 30 hari terakhir; Rendah = lainnya.',
        '• Produk bundle, kemasan/kantong dan item kafe dikecualikan. Data stok bergerak – cek ulang stok sumber sebelum membuat dokumen transfer.',
        f'• File ini dibuat otomatis setiap pagi oleh sinkronisasi Jubelio (dashboard penjualan & stok). Versi ini: {asof_s}.',
    ]
    for n in notes:
        ws.cell(row=r, column=1, value=n).alignment = TOPWRAP; ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=8); ws.row_dimensions[r].height = 30; r += 1
    _widths(ws, [16] + [15] * 7)

    # ---- 2. Rekomendasi Transfer
    ws = wb.create_sheet('Rekomendasi Transfer')
    ws['A1'] = 'Rekomendasi Transfer Stok – Toko Offline'; ws['A1'].font = F_H1
    ws['A2'] = f'Stok habis di toko tujuan, tapi laku di toko tsb (penjualan POS {win}). Sumber: toko lain dengan stok lebih (setelah sisakan ±1,5 bln kebutuhan sendiri).'; ws['A2'].font = F_SUB_SM
    head = ['Toko Tujuan', 'SKU / ISBN', 'Judul / Nama Produk', 'Merk'] + mlabs + ['Terjual 3 Bln', 'Penjualan Terakhir', 'Stok Tersedia di Toko Tujuan', 'Saran Qty']
    for i in (1, 2, 3): head += [f'Transfer dari #{i}', f'Stok Tersedia di Sumber #{i} (sebelum transfer)', f'Qty Transfer #{i}']
    head += ['Total Transfer', 'Kekurangan', 'Status', 'Prioritas', 'Sudah Dikirim? (isi)', 'Catatan']
    _head(ws, 3, head); nm = len(mlabs)
    date_col = 4 + nm + 2; status_col = len(head) - 3; prio_col = len(head) - 2
    for i, row in enumerate(rec, 4):
        _row(ws, i, row, date_cols=(date_col,), center_from=5)
        ws.cell(row=i, column=status_col).fill = FILL_OK if row[status_col - 1] == 'Penuh' else FILL_PART
        pc = ws.cell(row=i, column=prio_col)
        if row[prio_col - 1] == 'Tinggi': pc.fill = FILL_HIGH
        elif row[prio_col - 1] == 'Sedang': pc.fill = FILL_MED
        ws.cell(row=i, column=len(head)).alignment = Alignment(horizontal='left')
    ws.freeze_panes = 'D4'; ws.auto_filter.ref = f'A3:{get_column_letter(len(head))}{max(4, 3 + len(rec))}'
    _widths(ws, [13, 16, 42, 14] + [8] * nm + [8, 12, 10, 8, 14, 12, 8, 14, 12, 8, 14, 12, 8, 9, 10, 10, 10, 12, 40])

    # ---- 3. Daftar Transfer per Rute
    ws = wb.create_sheet('Daftar Transfer per Rute')
    ws['A1'] = 'Daftar Transfer per Rute (untuk dokumen transfer di Jubelio)'; ws['A1'].font = F_H1
    ws['A2'] = 'Urut per toko asal → toko tujuan. Qty = saran transfer; stok sumber belum dikurangi transfer lain.'; ws['A2'].font = F_SUB_SM
    head = ['Dari', 'Ke', 'SKU / ISBN', 'Judul / Nama Produk', 'Qty Transfer', 'Stok Tersedia di Sumber (sebelum transfer)', 'Terjual 3 Bln di Sumber', 'Terjual 3 Bln di Tujuan', 'Prioritas']
    _head(ws, 3, head, fill=FILL_HEAD_GREEN)
    for i, row in enumerate(routes, 4):
        _row(ws, i, row, center_from=5)
        pc = ws.cell(row=i, column=9)
        if row[8] == 'Tinggi': pc.fill = FILL_HIGH
        elif row[8] == 'Sedang': pc.fill = FILL_MED
    ws.freeze_panes = 'A4'; ws.auto_filter.ref = f'A3:I{max(4, 3 + len(routes))}'
    _widths(ws, [14, 14, 16, 42, 10, 14, 12, 12, 10])

    # ---- 4. Perlu Restock
    ws = wb.create_sheet('Perlu Restock (Tanpa Sumber)')
    ws['A1'] = 'Habis & Laku, tapi Tidak Ada Sumber Transfer'; ws['A1'].font = F_H1
    ws['A2'] = 'Terjual ≥2 dalam 3 bulan. Kandidat restock dari supplier (atau cek stok Pameran).'; ws['A2'].font = F_SUB_SM
    head = ['Toko', 'SKU / ISBN', 'Judul / Nama Produk', 'Merk'] + mlabs + ['Terjual 3 Bln', 'Penjualan Terakhir', 'Saran Qty', 'Stok di Pameran', 'Prioritas']
    _head(ws, 3, head, fill=FILL_HEAD_DARK)
    for i, row in enumerate(restock, 4):
        _row(ws, i, row, date_cols=(4 + nm + 2,), center_from=5)
        pc = ws.cell(row=i, column=len(head))
        if row[-1] == 'Tinggi': pc.fill = FILL_HIGH
        elif row[-1] == 'Sedang': pc.fill = FILL_MED
    ws.freeze_panes = 'D4'; ws.auto_filter.ref = f'A3:{get_column_letter(len(head))}{max(4, 3 + len(restock))}'
    _widths(ws, [13, 16, 42, 14] + [8] * nm + [8, 12, 8, 10, 10])

    wb.save(path)
    return {'stores': per_store, 'transfer_rows': len(rec), 'route_rows': len(routes), 'restock_rows': len(restock)}
