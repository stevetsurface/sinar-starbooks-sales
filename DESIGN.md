# Design direction: Sales & Stock Dashboard

Reading this as: an internal operations dashboard for store, finance and management staff of a bookstore group, read every morning on phones and laptops, in the Wonder Bookstore retail identity (forest green, cream, wood accent, uppercase Archivo headlines, Inter body, pill buttons, the ↗ motif), the same language as wonder-bookstore's website and the airport proposal deck. Dial: ENERGY 1 / RHYTHM 2 / MOTION 1.

Why those dials: the page is read for numbers, not persuasion (ENERGY 1). Sections vary by what the data needs (tiles, charts, tables, a download card) but keep one card grammar so a store manager can scan it the same way every day (RHYTHM 2). Nothing moves except hover and focus states; motion would slow a daily check (MOTION 1).

## Decisions and their reasons (one line each)

- Palette: Wonder Bookstore forest green `#0F2D24` (header, headings, emphasis), cream `#F3EFE6` page with white cards, wood `#C89B5A` as the single accent (KPI tile rule, focus ring, stale-data dot). Taken from the Wonder Bookstore website tokens, because this is the retail side's tool. Chart series: green for Wonder Bookstore, wood for Sinar Starbooks, slate `#6B7F8A` for Kikkerland, the third only because three brands share one chart.
- Semantic colours: green `#1F7A4D` up, red `#B8362A` down, amber `#8A5600` warning. All pass 4.5:1 on white and on cream.
- Typography: Archivo, weight 500, uppercase with tight tracking for the title, card headings and the big KPI numbers, the Wonder Bookstore headline voice; Inter for everything else because it stays legible at 12 to 13 px in dense tables. Tabular numerals throughout so columns line up.
- Small uppercase labels (tile labels, table headers, "Insight"): tracking 0.7 to 1.4 px, 10 to 11 px. They separate a label from the value under it in dense tiles. No large uppercase headings anywhere.
- Cards with 10 px radius (the Wonder site's radius token), a 1 px cream border and no shadow: panels need edges on a cream page; shadows are reserved for the login dialog and chart tooltips, which do float.
- Pill shapes only on controls (segment buttons, Excel/download buttons, the sync link), as on the Wonder site: pill = "press me", rectangle = content. Inputs are 10 px, cards and tiles 10 px, tiles with a 3 px wood top rule marking them as headline numbers.
- Header is solid forest green with white and cream text, like the site header: one focal point per screen is the title plus the data-freshness line; the green block gives the page its identity without decoration.
- The arrow on "Sync data": it leaves the site and opens GitHub in a new tab; the arrow says so, and ↗ is the Wonder Bookstore button motif.
- The dot before every "updated" time is a status light: green under 36 h since the last sync, amber up to 3 days, red beyond. It replaces a decorative dot with a meaning.
- Excel buttons carry a small green sheet glyph so the eye finds "export" in a crowded card header. No other icons on the page; where none is relevant, none is used.
- No dark mode: the page is read in bright shops and printed into WhatsApp screenshots; the brand surfaces are cream and white. Documented choice, not deferred work; revisit if staff ask for it.
- Empty, loading and error states: every card shows a skeleton while loading, a muted failure line on fetch error, and "No data for this selection" in tables.
- Mobile: single column, controls at least 44 px tall under 600 px, tables scroll inside their card so the page never scrolls sideways.
- Keyboard: every control is a real button, link, select or input; focus shows a 3 px wood ring (white on the green header).
- Copy: Indonesian first, English second, plain sentences, no marketing words. Numbers are Jubelio's; where Jubelio has no data (cost price, Tokopedia fees, POS quantities) the guide says so instead of estimating.

## Things this page deliberately does not have

Hero section, feature grid, testimonials, pricing, "trusted by" bar, gradients, glows, background patterns, animations, illustrations, generic icons.
