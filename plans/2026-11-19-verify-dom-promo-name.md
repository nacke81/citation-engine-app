# Plan: Verify DOM check follow-up, promo/referral name with an "Enter code" label (t_8f631f1b)

Cites lesson `docs/lessons/2026-11-18-two-sources-one-page-must-agree.md` (latest at start): a new source (the aria/placeholder human-label rule) must not override a value the same input shows wrong (its name/id).

## Gate evidence (read, no live reads/sends)
First real post-#128 Verify Now: NM Thumbtack, request db1fdaaa, outcome `verified`. verify-send log has no `sent refused` line, so no refusal shapes exist. Evidence files 01-04 are page text only; the input attributes of Thumbtack's code box were not logged on a clean run.

## Item 1 (build)
`rule_named_code` ran NOT_A_CODE only on the number rule. A `name="promo"` + `placeholder="Enter code"` input hit `_human_code` and read LANDED.
Change: in `rule_named_code`, return False when name or id hits NOT_A_CODE, unless that name/id is itself a code field by `_field_is_code` (so `phoneVerificationCode` as a name still records; `_phone_first` stays aria/placeholder only).
Tests (verify_dom_test.py, section 16): promo/coupon/referral/invite/zip names with `Enter code`/`code` labels refused (by name and by id); phoneVerificationCode name and name=otp still record; name `code` + `Enter code` still records. Mutations: guard removed; guard applied with no `_field_is_code` exception (phoneVerificationCode lost).

## Item 2 (decision: no rule)
No live Directory shape shows type=number: the only real run (Thumbtack) recorded cleanly and logged no shapes, Alignable was done by hand. A rule from a guess is what the card forbids. Not built. Reopen when a `sent refused ... inputs seen:` line shows `number/-/N/...`. The unmatched shape stays over-refusal (safe direction).
