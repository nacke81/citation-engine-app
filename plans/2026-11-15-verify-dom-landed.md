# Plan: Verify Now DOM landed check (t_00a83602)

Cites lesson `docs/lessons/2026-11-15-quote-the-page-not-the-button.md` (latest at start): evidence must be a state the page shows after the act. Free text cannot tell "Press the button to send your verification code" from a landed page; a visible code input can. Based on PR #127 head 6e8260f (`landed()` lives only there; #127 is still open, so this branch is stacked on it).

## Where the CDP session is
`step_sent` (job/verify_step.py) runs as the agent's CLI, not inside the bridge send run; nothing in it holds a session. But the request row carries `client_id`, `portal.ALLOWED` maps it to the tenant (NM/SCC), and `verify_send.tenant_browser(biz)` already is the one record of the tenant's CDP URL (NM 9334, SCC 9333, loopback). `step_sent` opens a short read-only Playwright `connect_over_cdp` to that URL (same client `build_shot.py` uses), reads every input in every frame of every page, and closes without touching the page. It never clicks, types, or navigates.

## Selector rule (job/verify_dom.py, pure Python over a snapshot, so tests use fake snapshots)
An input counts when it is visible AND enabled AND not readonly, type in text/tel/number/password/search/(none), and one of:
1. `autocomplete=one-time-code`
2. `inputmode=numeric|decimal` + `maxlength` 4-8 (and no excluded word below)
3. name/id/aria-label/placeholder contains `code|otp|verif` (and no excluded word)
4. a row: 4-8 inputs sharing one parent, each `maxlength=1`

Excluded words (rules 2, 3 only; rule 1 is explicit and always wins): zip, postal, phone, tel, promo, coupon, referral, invite, country, area, card, cvc, cvv, ssn, year, exp. A phone box or ZIP box must not read as a code box.

## Combine rule
- Error/refusal evidence paths run first, unchanged (SEND_REFUSAL fails the request; other error words refuse).
- Probe returns None (tenant unknown, no Playwright, Chrome unreachable, any exception, CE_NO_CDP set) -> fall back to `landed(text)`; log `dom unavailable`.
- Probe returns a snapshot with a code input -> landed, even if the text is not recognised ("A 6-digit code is on its way to your phone"). Evidence text must still pass `clean_evidence`.
- Probe returns a snapshot with NO code input -> REFUSED, nothing recorded, whether or not the text says landed. Log says which: `dom: no visible code input (text said landed)` / `(text did not either)`.
- A no-input snapshot is re-read up to 3 times, 1 s apart, before refusing (a code box can render a beat after the click). Fail-open only on "cannot see", never on "saw none".
- Nothing from the page leaves the probe except attribute fields; the log carries reason words only.

## Tests (tests/verify_dom_test.py new, plus tests/verify_speed_test.py)
- Fake snapshots: each of rules 1-4 alone records code_sent; phone box, ZIP box, hidden/disabled/readonly code box, 3- and 9-box rows, page with no inputs are refused.
- The 4 strings from the card are refused when the DOM shows no code input (and still recorded when DOM is unavailable = today's behaviour, pinned); "A 6-digit code is on its way to your phone" records with a code input.
- No-session fallback, probe-exception fallback, re-read count.
- Mutations: each rule removed (its own fixture then refused), visible check removed, enabled check removed, exclusion list removed, no-input-refuse removed (text-landed + no input records).
- 10c: "Send code / Enter code" records; mutation 10m drops `/` from CLAUSE and 10c catches it.
- verify_fakes sets CE_NO_CDP=1 so no suite ever touches a real Chrome.

## Not in scope / risks
Combine rule follows Nate's proposal on the card; no plan-review stop taken. Risk: a Directory whose code box is not an `<input>` (contenteditable) is refused when the probe sees the page. That surfaces as a refused `sent` (nothing recorded), the visible failure mode, not a false send. No live reads or sends in this card.
