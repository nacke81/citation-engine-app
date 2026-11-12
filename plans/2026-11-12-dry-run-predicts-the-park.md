# Plan: recheck.py dry run predicts the 3/3 no-URL park (t_bee96b30)

Cites lesson `docs/lessons/2026-11-11-two-readers-of-one-page-must-share-one-block.md`: two paths over one decision must share one block. Here the dry run and `--backoff-only` are two readers of the same cap rule; the dry run returned before the rule.

Scope (Nate decided: the 3/3 park stays; only prediction + docs change), `job/recheck.py` only:
1. `_backoff()`: on a dry run (`not write`) for a no-URL row in a waiting state, run the same two checks as the write path before returning: not-due (due date in the future) -> date unchanged, `not_due`, no park; else `no_url_backoffs >= MAX_NO_URL_BACKOFFS` -> `after=needs-human`, `would_park=no-public-permalink`, `recheck_due=None`. Nothing is written.
2. `format_report`: print `-> needs-human (would park: no-public-permalink)` and `recheck_due <old> -> none (dry run: not stored)`.
3. `--backoff-only` help text and the `bw` comment: it may park a row after 3 no-URL backoffs.

Tests: new `tests/recheck_dryrun_park_test.py` (fakes only, 404 plain fetcher, no network), wired into CI: dry run with 2 and 3 prior backoffs (prediction == what --backoff-only then writes), not-due path, nothing written, help text. Mutation check: drop the prediction, a test fails.

Lesson to write after: `docs/lessons/2026-11-12-a-dry-run-runs-the-same-rules.md`.
