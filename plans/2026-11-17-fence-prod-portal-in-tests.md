# Plan: no test reaches the prod portal (t_2ddc7067)

Cites lesson `docs/lessons/2026-11-17-count-it-but-do-not-claim-it.md` (latest at start): when a count and a claim come apart, follow the value through every consumer. Here: a test "pass" and a prod write came apart, so the fix must follow the creds to every importer, not only the two files seen.

## Finding (execution, base ba4475d, network trap logging + refusing non-loopback)
`portal.load_portal_env()` reads creds from `CE_PORTAL_ENV`, else `%LOCALAPPDATA%/citation-engine/portal_env_path.txt` -> prod `.env.prod.local`. CI has neither, so it never showed. Two tests build the REAL client because they call `B.main(...)`, which does `P.Portal(*P.load_portal_env())`:
- `tests/verify_bridge_test.py` L34 via `quiet(B.main, [])` (run_pass -> sweep/first_use/claim: GET citation_code_request x3, GET citation_verification x1, **POST rpc/claim_code_request x1**) and L353 `quiet(B.main, ["--check"])` (GET citation_code_request, counted in the 3).
- `tests/verify_agent_test.py` L67 `quiet(B.main, ["--check"])`: GET citation_verification x1 (via verify_bridge.py L523 sweep path).
Trap counts on base: bridge 5, agent 1.

## Change (tests only; no job/ change, prod behavior untouched)
1. Fence: `os.environ["CE_PORTAL_ENV"] = <TMP>/no-such.env` before the first portal/verify_bridge import, in both files and in every other tests/*.py that imports portal / verify_bridge / verify_now (so the real client fails closed at open(), before any request). verify_agent_test already passes it to a subprocess only.
2. Guard: new `tests/no_prod_portal_sink_test.py` (sibling of #131's scan, added to CI): ast scan; a file importing portal / verify_bridge / verify_now must set CE_PORTAL_ENV to an expression containing a `no-such` string constant before the first such import, and may never pop/delete it. Synthetic negative paths test the scanner.
3. Proof: both tests under the trap at head -> 0 requests; base -> 5 + 1. Scan on base copy -> names both files. Whole portal-importing set under trap, head.
4. Read-only prod check: GET citation_code_request state=starting rows, report only.

## Not doing
No prod write, no cleanup of any claimed row (needs-mike if found).

## Result
- 35 test files fenced (one line before the first portal/verify_bridge import); `tests/no_prod_portal_sink_test.py` added to CI: base 9/10 naming verify_agent_test.py + verify_bridge_test.py (35 offenders), head 10/10.
- Trap over all 106 CI commands at head: 0 non-loopback requests. verify_bridge_test rc0, 0 requests (base 5 incl POST rpc/claim_code_request). verify_agent_test 0 requests (base 1); its rc1 (prompt-holds-no-code, 2 FAILs) is identical on base, pre-existing, not touched here.
- Read-only prod GET citation_code_request: 3 rows total (failed 2, could_not_start 1), none requested/starting/code_sent/checking. No row claimed by a local run is visible.
- Lesson: `docs/lessons/2026-11-17-creds-outside-the-env-need-a-fence.md`.
