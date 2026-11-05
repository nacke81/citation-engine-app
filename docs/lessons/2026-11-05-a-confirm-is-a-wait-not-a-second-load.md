# A confirm is a wait inside the load, not a second load

Lesson from t_0c4ebee8. Cites docs/lessons/2026-11-05-count-requests-not-code-paths.md.

The guard log showed 2 reservations for one promotion, and the tests said "one confirming read". Mike watched four Chrome loads. Three things hid it: the same-process shortcut skipped the guard gap for the confirm read; the dry run and `--write` each read from scratch; and the Chrome window sat on his screen so every load was seen.

- Stability against a late-rendering page is a property of ONE load: poll the same page ~3s apart and stop when the NAP holds still. A second load 30s later asks the Directory the same question twice and doubles the Cloudflare exposure.
- A write that follows a dry run should reuse what the dry run read (fresh, same URL), and say so in the test: count the loads, not the reservations.
- A headed reader is fine for Cloudflare but must open off-screen. Counting "loads" and "windows shown" are separate acceptance lines.
