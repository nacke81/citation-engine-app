# 2026-11-05: a verification run is a read of someone else's site; budget it like one

- Workers re-ran the full `--include-live` sweep about 15 times to check a one-row proof-string change, and each live row was read three times back to back. Bizapedia hit its free-search quota and every later read was ambiguous.
- A quota page is a 200 with ordinary text. Wall detection that only knows status codes and Cloudflare wording will score it as "not public". Detect the site's own redirect and wording, and make the verdict "stopped, nothing written", never a demotion.
- Before/after checks should replay saved pages. Anything that touches the network needs a per-domain gap, a daily cap and a cooldown kept in a file, because separate processes share the site's patience.
- A "same read" shortcut (plain then Chrome fallback on one URL) must be scoped to one process. The first version let a second process skip the gap; the live proof run exposed it.
- A test that drives a failing fake page can still write evidence into the real runs folder. Point `CE_RUNS` at a temp dir before importing and assert the real folder did not grow.
