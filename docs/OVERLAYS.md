# Flows: mixing pages, sorting and overlays

## Mix of pages and links (source type `multi`)
`source: {type:"multi", rights:true, sources:[{type:"page",url,max_items,backlog}, ..., {type:"links"}]}` (max 12 pages).
Each page is read on its own (`sources/multi.py`); one blocked page never stops the others. Items carry `src_i` and `meta.from`.
Instagram pages use the Save-to-Drive ladder (`igarchive.py`) first when the flow sorts/filters by numbers, otherwise yt-dlp first.
Downloads that yt-dlp cannot do fall back to `igarchive.fallback_download`.

## Order and filters (`route.order`, `route.filters`)
Order: oldest, newest, views_high, views_low, likes_high, posted_new, posted_old, mix (take turns between pages), random, manual.
Videos with no number/date go last. Filters: min/max_views, min_likes, within_days, older_than_days, date_from/date_to,
min/max_seconds, include/exclude words, `unknown: allow|skip`. "Post first" videos ignore filters.
Views/likes/date are known only where the listing way provides them (Instaloader, Apify/RapidAPI, gallery-dl JSON, YouTube). Not live-tested.

## Overlays (`route.edit.layers`, `edit.canvas.bg`, `edit.reel_box`)
Layers stack bottom to top above the video. Types: `frame` (coloured screen with a see-through window), `image` (PNG keeps transparency; `asset:<file>` in data repo `assets/` or https), `box`, `text`.
Text: font (sans-bold, sans, serif-bold, mono-bold, clean-bold, clean-serif, narrow-bold, rounded-bold, hindi, custom .ttf link), size, colour, outline, shadow, strip, align, fade in/out, `clip_to:<frame id>` = text only shows inside that window.
Variables: {title} {n} {date} {author} {views} {likes}. Rendering is `layers.py` + `media.prepare` (ffmpeg). The editor can preview with a sample video from the owner's device (never uploaded) and layers can be dragged.
Fonts: workflows install DejaVu, Liberation and Lohit Devanagari. Not verified on the real runner.
