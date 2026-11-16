# Plan: LANDED_TEXT must not accept a send button label or a negated send (t_6168a061)

Cites lesson `docs/lessons/2026-11-15-fail-only-on-a-refusal.md` (latest at start): a gate is only as good as the mutation that proves it. Follow-up to PR #124 review.

Note: the plan file was written after the first source edit (process slip, disclosed on the card); the tests were written before the full-suite run.

## Changes
1. job/verify_step.py: LANDED_TEXT drops the bare `verification code|confirmation code|security code`. A code name counts only as: `<X> code (was) sent/texted/emailed`, `we sent/texted ... code`, `enter/type/input (the|your|a) [N-digit] [X] code`, `code field/box/input`. `NEGATED_SEND` cuts "not/never/no/n't ... sent/send/texted" clauses before the search (`landed()`).
2. tests/verify_speed_test.py section 10: 6 refused strings (incl. the 3 from the card + "Text me a code"), live Thumbtack text stays code_sent, 5 landed-context strings recorded, Alignable stays failed/send_failed, prompt carries the quote-only line, mutations: bare alternative restored (10f), negation ignored (10g), quote-only line removed from verify_send.py (10h).

No portal write, deploy, or live read.

## Round 2 (review changes_requested, PR #127 head 3e7fe74)
- LANDED_TEXT: one optional adverb slot (`just|now|already|successfully`) in the `we sent` and `code (was|has been) sent` forms; curly apostrophe accepted in `we've`.
- NEGATED_SEND now cuts only a negation that governs the verb: `not/never/n't` + optional auxiliaries/`yet`/`been` + sent/send/texted, `yet to send`, and `no ... code (was|has been)? sent`. "No worries, we sent a code" and "Don't close this window, we texted you a code" stay landed.
- Tests: 5 more landed strings in 10c; mutation 10i removes the adverb slot and fails 10c's "We just sent you a code".
