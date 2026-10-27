# Lesson 2026-10-27: one read path for dry run and write, and keep the evidence before the context closes

Card t_03a74bae (batch 17 problems). Four gaps made batch 18 depend on hand steps:

- A dry run said `match` and `--write` said `nap-incomplete address` on the same row. Both already called one loop, so the flip came from the READ: the plain GET kept a name-only shell of a JS page, the rendered read took the first render (the street lazy-loads), and only a `match` was repeated. Fix in the one function both call (`recheck.read_listing`): a plain page that is not a full match goes to the rendered read, the rendered read waits for the NAP (or for the text to hold still), and any disagreement among 3 reads is never live. Test it with a fixture where the street appears late, run in both modes.
- `--only` ran on a blank page. A subset run must start from the same place a full run does: the spec's open/sign-in step runs first, and a spec without one fails loudly.
- A failed step closed the context with the page still in it. Save screenshot + URL + redacted text excerpt inside the runner, before the caller closes anything.
- A click whose result is never read is a wasted daily try (citylocalpro re-send). A spec that spends a limited action must also read and classify the answer (`read_result`: sent / limit / unknown), and judge only text that is new since the click.

Also: status paths belong in data (`MAIL_ONLY`, `status_path`), not in a batch card's prose. Specs left untracked in a runtime clone break the self-update; commit what earns its place, delete the rest.
