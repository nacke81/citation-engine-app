# Plan: t_0c4ebee8 recheck: fewer, spaced Chrome loads; Chrome off Mike's screen

Cites docs/lessons/2026-11-05-count-requests-not-code-paths.md: count the loads actually made (Chrome page loads, by URL), not the guard reservations. The guard log showed 2 reservations but Chrome loaded 4 times.

Base: main 9fcb7b2. Branch feat/recheck-fewer-loads-t_0c4ebee8.

## Decisions
1. Confirm read: REPLACE with one load that waits for the NAP to be stable (chosen over "second guarded read 30s later").
   Why: the instability being guarded against (t_03a74bae, a street that renders late) is a rendering race inside one page load; a second load 30s later costs a second hit on the Directory for the same information and doubles the Cloudflare exposure. `read_rendered` stops only when the NAP matches AND the body text is unchanged across 2 polls 3s apart (max 20s once readable). `read_listing` makes ONE chrome load. OSM (API tags, no page load, other host) keeps its STABLE_READS confirm.
2. `--write --from-read DIR`: PageStore gets a `fresh()` replay: a saved page is reused only if file mtime < 15 min and its saved `url` equals the URL requested (the file name carries sha1(url), the body is re-checked). The reuse sits INSIDE the guard wrapper's inner side (before the network and before reserve), so a reuse makes no reservation and no load. Anything stale / missing / URL-mismatched falls through to the live reader (one guarded read as today). `--from-read` needs `--write`, refused with `--replay`.
3. Visibility: `OwnedChrome` (recheck's signed-out reader) and `chrome_keepalive.chrome_args` (build Chrome 9333) start with `--window-position=-32000,-32000`. Env `CE_CHROME_VISIBLE=1` restores 40,40. Proof: one already-live row, 1 read through the guard, window rect recorded off-screen, Cloudflare passes.

## Tests (no network)
- fake clock: a stability poll loop spaces polls 3s and ends by 20s; the chrome reader is called once for a not-yet-live row.
- write from a fresh saved read: 0 plain / chrome reads, row goes live.
- stale (mtime) saved read: 1 read. URL-mismatched saved read: 1 read.
- update S1 / R6 / A2 call counts from STABLE_READS to 1 for chrome.
