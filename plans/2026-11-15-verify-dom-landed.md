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

## Round 1 review changes (Nate, comment 785)
- Scope: every snapshot item carries its page URL; pages with no inputs still count as seen. `step_sent` hands the probe the Directory's domain + aliases (`B.directory_entry`). Only pages whose host is the domain or a subdomain count. No page on the domain = refused, nothing recorded, log says pages seen / matched. No fallback to text. Unlisted Directory (no domains) = nothing in scope = refused.
- Named-code rule: token allowlist (split on case change, `_ - space`). Match: otp/totp/passcode; `code` adjacent to verification/verify/security/confirmation/sms/auth/one-time; compound tokens (verificationcode, smscode...); a name/id exactly `code`. Never with `captcha` in the label; a password box only with otp/passcode. Numeric+maxlength rule also excludes captcha.
- Tests 13a/13b (18 leaks refused, 15 real shapes recorded), 14a-14h (host scope), mutations: substring rule back, captcha guard off (named and numeric), password guard off, bare-code token, host filter removed / substring / exact-only.

## Round 3 review changes (Nate, comment 787, last label round)
- `_human_code` (aria/placeholder only): a bare `code` with only filler words around it records (`Enter code`, `6-digit code`, `Code`, `Enter the code we sent to your phone`).
- `_phone_first` (aria/placeholder only, never name/id): a phone/email word before any code word = the phone field, refused. `phoneVerificationCode` as a name still records.
- `NOT_CODE_TOKENS` on the numeric+maxlength rule: postcode/employees/house_number/naics etc. refused.
- Refusal log lists up to 5 usable inputs of the Directory's pages as `type/inputmode/maxlength/autocomplete/name|id|aria|placeholder` (attributes only, no values), kept in `VD.LAST["shapes"]`.
- Test 13b (placeholder `code`) now asserts True. New 15a-15d plus mutations: `_human_code` removed / accepts anything, `_phone_first` removed, `NOT_CODE_TOKENS` emptied.
- Known limit (card design, not a defect): a page that shows the code box before the send click (phone field, Send button and code box on one screen) records a sent from the DOM, whatever happened.
- Any new label family after this round is a follow-up; the refusal log is how real shapes get collected.
