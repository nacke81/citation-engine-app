# Plan: Verify DOM check follow-up, promo/referral name with an "Enter code" label (t_8f631f1b)

Cites lesson `docs/lessons/2026-11-18-two-sources-one-page-must-agree.md` (latest at start): a new source (the aria/placeholder human-label rule) must not override a value the same input shows wrong (its name/id).

## Gate evidence (read, no live reads/sends)
First real post-#128 Verify Now: NM Thumbtack, request db1fdaaa, outcome `verified`. verify-send log has no `sent refused` line, so no refusal shapes exist. Evidence files 01-04 are page text only; the log carries no input attributes on a clean run (they are in the submitter session, see item 2).

## Item 1 (build)
`rule_named_code` ran NOT_A_CODE only on the number rule. A `name="promo"` + `placeholder="Enter code"` input hit `_human_code` and read LANDED.
Change: in `rule_named_code`, return False when name or id hits NOT_A_CODE, unless that name/id is itself a code field by `_field_is_code` (so `phoneVerificationCode` as a name still records; `_phone_first` stays aria/placeholder only).
Tests (verify_dom_test.py, section 16): promo/coupon/referral/invite/zip names with `Enter code`/`code` labels refused (by name and by id); phoneVerificationCode name and name=otp still record; name `code` + `Enter code` still records. Mutations: guard removed; guard applied with no `_field_is_code` exception (phoneVerificationCode lost).

## Item 2 (decision: no rule)
Decision evidence: citation-submitter state.db msg 15840 (18:19:31Z, request db1fdaaa) focuses `#pin-input-0`, and msg 15843 reads `#pin-input-0..3`. The one live code box (Thumbtack) is a 4-box pin row, matched by `single_char_row`, not one type=number box. Alignable was done by hand. No rule; a rule from a guess is what the card forbids. Pinned by test 16c (the row, and the row with type=number). Reopen when a `sent refused ... inputs seen:` line shows `number/-/N/...`. The unmatched shape stays over-refusal (safe direction).
