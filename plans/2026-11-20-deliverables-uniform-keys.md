# Plan: deliverables batch POST 400 (mixed key sets) + readable portal HTTP errors (t_e9ea1429)

Cites lesson `docs/lessons/2026-11-20-two-writers-one-must-not-be-silent.md` (latest at start): a failure that prints nothing useful is as bad as a silent one, so the 400 must name its PostgREST code.

## Cause
PostgREST refuses a bulk insert whose JSON objects have different keys (PGRST102, HTTP 400). The NM backfill batch had 18 rows with `evidence_url` and 1 (the Verify Now `...:verified` row) without. Any live or backfill batch that mixes the two shapes fails. The 400 text was only `HTTP Error 400`.

## Items
1. `portal.uniform_rows(rows)`: union of keys over the batch, missing key = None, first-seen key order. Applied in the ONE shared place: `write_deliverables`, `deliverables_request` (dry run) and `guard_deliverables` (the transport choke point, so a caller that bypasses the helper is still uniform). No backfill special case.
2. `Portal.call` catches `urllib.error.HTTPError`, reads at most 4 KB of the body, parses JSON, and keeps only `code` and `message` (allowlist), each capped (code 40, message 200 chars), scrubbed of the key. Never the request body or headers. Unparseable body: status only.
3. Tests (`tests/deliverables_helper_test.py`): mixed batch uniform in all three paths; mutation removing the normalization fails; fake opener raising HTTPError(400, PGRST102 body) puts `PGRST102` and the message in the error; a body carrying extra fields (details, hint, the key) leaks none of them; text is capped.

## Not done
No prod write, no backfill run (t_ff25e10b re-runs `--write` after merge).
