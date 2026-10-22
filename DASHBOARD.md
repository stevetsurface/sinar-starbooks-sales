# Sales & stock dashboard

Live dashboard: https://stevetsurface.github.io/sinar-starbooks-sales/ (public; also a private copy on claude.ai)

Tabs: Ringkasan (overview) · Penjualan & toko · Produk · Reseller · Stok · Keuangan · Panduan (guide). Indonesian / English switch, brand filter, online vs store filter, period picker, Excel export on every list.

## Which file feeds which part
| File in `data/` | Used for |
|---|---|
| sales_daily_detail.csv | All sales numbers, trends, channel & store tables (since Oct 2025) |
| hour_dow.csv | Busy-hours heatmap (90 days) |
| titles_daily.csv, items.csv | Produk tab: best sellers, rising titles, categories (90 days) |
| finance_daily.csv, cancel_reasons.csv | Keuangan tab (90 days) |
| customers_90d.csv | Repeat customers |
| stock_*.csv | Stok tab: per-location situation, running out, oversold, low stock, fast movers, dead stock, transfers |
| snapshots.csv | "Updated" time shown on every card |

Reseller data (resellers.csv, reseller_tracker.csv) comes from the Sinar Star reseller files, not Jubelio, and is not produced by this sync.

## Definitions
- Revenue = Jubelio order grand total, excluding cancelled/returned (Shopee is already net of service fee).
- Store (offline) = Jubelio POS. Online = marketplaces. Online orders shipped from a store count in that store's "Online" column.
- Oversold = reserved by orders > on hand at a location (available below zero).
- Dead stock = no sale in 90+ days. Stock value is at selling price (HPP is empty in Jubelio).

## Daily flow
1. 04:00 WIB: GitHub Action runs `scripts/jubelio_sync.py` and commits `data/`.
2. A Claude scheduled task then loads the new files into the dashboard.

Needs repo secrets `JUBELIO_EMAIL` and `JUBELIO_PASSWORD` (view-only Jubelio user).
