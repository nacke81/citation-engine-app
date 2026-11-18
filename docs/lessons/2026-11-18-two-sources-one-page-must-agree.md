# Lesson: when a page shows an address twice, use the complete one only if nothing else on the page contradicts it (t_59f339e5)

localstar showed the address twice: a partial Address Details block and a complete Full Address row. The reader took only the block and read nap-incomplete for a week. The first fix (use the row) passed the planned tests but made a page whose block said a different city match, because the row was trusted alone. A check that closes a gap must also run the checks the gap was hiding from: the supplement now stays off when the block under the street names another city, and every part of the row is compared (street, city, state, ZIP).

Rule: a new source may fill a gap, never override a value the page itself shows wrong. Add the contradiction case in the same test file as the match case.

Dry-run note: `--include-live` over the whole queue skips rows not yet due (localstar: recheck due 11-25), so the full-sweep diff cannot show a skipped row. Read that row with `--row ID` too, saved once with `--save-pages` and replayed on main and head so both read the same page.
