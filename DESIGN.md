# Design direction: Sales & Stock Dashboard

Reading this as: an internal operations dashboard for store, finance and management staff of a bookstore group, read every morning on phones and laptops, in the Wonder Bookstore brand language (deep purple, gold, serif headings). Dial: ENERGY 1 / RHYTHM 2 / MOTION 1.

Why those dials: the page is read for numbers, not persuasion (ENERGY 1). Sections vary by what the data needs (tiles, charts, tables, a download card) but keep one card grammar so a store manager can scan it the same way every day (RHYTHM 2). Nothing moves except hover and focus states; motion would slow a daily check (MOTION 1).

## Decisions and their reasons (one line each)

- Palette: purple `#5B2A86`, gold `#F2B33D`, lilac surfaces `#F4F0F8`. The brand's own colours; purple is the header and emphasis, gold is the single accent (KPI tile rule, freshness dot, focus ring), lilac separates panels from the white cards. A third series colour `#2E5F8A` exists only because charts show three brands at once.
- Semantic colours: green `#1F7A4D` up, red `#C0392B` down, amber `#8A5600` warning. All pass 4.5:1 on white.
- Typography: Fraunces (serif) for titles and big numbers because the brand is a bookstore and the serif carries that; Figtree (sans) for everything else for legibility at 12 to 13 px in dense tables. Tabular numerals throughout so columns line up.
- Small uppercase labels (tile labels, table headers, "Insight"): tracking 0.7 to 1.4 px, 10 to 11 px. They separate a label from the value under it in dense tiles. No large uppercase headings anywhere.
- Cards with 16 px radius and a 1 px border, almost no shadow: panels need edges on a lilac page; shadows are reserved for the login dialog and chart tooltips, which do float.
- Pill shapes only on controls (segment buttons, Excel/download buttons, the sync link): pill = "press me", rectangle = content. Inputs are 10 px, cards 16 px, tiles 16 px with a 3 px gold top rule marking them as headline numbers.
- Header is solid purple with white text: one focal point per screen is the title plus the data-freshness line; the purple block gives the page its identity without decoration.
- The arrow on "Sync data": it leaves the site and opens GitHub in a new tab; the arrow says so.
- The dot before every "updated" time is a status light: green under 36 h since the last sync, amber up to 3 days, red beyond. It replaces a decorative dot with a meaning.
- Excel buttons carry a small green sheet glyph so the eye finds "export" in a crowded card header. No other icons on the page; where none is relevant, none is used.
- No dark mode: the page is read in bright shops and printed into WhatsApp screenshots; the brand surfaces are light. Documented choice, not deferred work; revisit if staff ask for it.
- Empty, loading and error states: every card shows a skeleton while loading, a muted failure line on fetch error, and "No data for this selection" in tables.
- Mobile: single column, controls at least 44 px tall under 600 px, tables scroll inside their card so the page never scrolls sideways.
- Keyboard: every control is a real button, link, select or input; focus shows a 3 px gold ring (white on the purple header).
- Copy: Indonesian first, English second, plain sentences, no marketing words. Numbers are Jubelio's; where Jubelio has no data (cost price, Tokopedia fees, POS quantities) the guide says so instead of estimating.

## Things this page deliberately does not have

Hero section, feature grid, testimonials, pricing, "trusted by" bar, gradients, glows, background patterns, animations, illustrations, generic icons.
