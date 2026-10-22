# Sinar Starbooks / Wonder Bookstore sales data

Daily export from Jubelio (Wonder Bookstore account, which also holds the Sinar Starbooks marketplace shops) for the sales & stock dashboard.

- `scripts/jubelio_sync.py` logs in to Jubelio, pulls orders since Oct 2025, order details for the last 90 days (cached in `cache/`) and the inventory alert lists, and writes CSVs to `data/`.
- `.github/workflows/daily-sync.yml` runs it every day at 04:00 WIB and commits the new files. Run it by hand from the **Actions** tab ("Run workflow").

## Setup (once)
Settings → Secrets and variables → Actions → New repository secret:
- `JUBELIO_EMAIL` – a view-only Jubelio user created for this sync
- `JUBELIO_PASSWORD` – its password

This repository is public and served with GitHub Pages: index.html is the dashboard and reads data/*.csv. Everything here, including sales and reseller data, is visible to anyone with the link.
