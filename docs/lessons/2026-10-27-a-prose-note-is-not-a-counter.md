# Lesson 2026-10-27: a try written as prose did not count

Card t_bbc32230. The hard-block cap counted only history entries with a structured `wall` field. The 10/26 cylex try had been written by hand as a note, so on 10/27 the counter read 1 and the cap would have allowed one extra day.

- When a cap counts events, test it against the real shape of the data already in the queue, not only the entries the new code writes. Read a real row first (read-only).
- A hidden/paused banner next to a full NAP is a verdict (`not-public`), not a gap. Decide the verdict by what the page says about visibility before it compares fields.
- A URL from an outside source (mail) goes through the same permalink gate as every other URL before it is stored, and is stored in the field the reader uses (`listing_url`).
- When no public source exists, say so with a verdict (`unreadable-public`) instead of retrying or reading signed in.
