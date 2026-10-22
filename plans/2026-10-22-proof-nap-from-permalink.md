# Plan 2026-10-22: quote proof_nap from the proof_url page (kanban t_2971077b)

Latest lesson read: none exist (no docs/lessons). Prior plan: plans/2026-10-22-weekly-proof-writer.md (PR #15). Applied from it: never write a live row without proof_nap, and never over-count.

Defect: proof_url is the permalink `lurl`, but proof_nap/verdict came from the matched page `u`. When u != lurl they are different pages.

Design
- run.build(): when lurl and lurl != u, build a local `_proof` dict from the permalink page's text (claim.pick_page text, only when the page really is lurl): nap (nap_lines), name/street/phone/match flags (core.evidence -> judge.nap_flags) and diffs (fixlist.diffs_for). If the permalink text is missing/blank, `_proof` has nap=None and no flags. `_proof` is local; directories.py/portal.py never read it. u == lurl: no `_proof`, behavior unchanged.
- proof.verdict()/proof_step(): when `_proof` is present, the verdict and the written proof_nap come from it. Missing/blank permalink NAP -> verdict None -> nothing written.
- No Directory traffic added.

Golden tests (tests/proof_test.py): (1) u != lurl, permalink matches -> proof_nap is the permalink's NAP, not the matched page's. (2) u != lurl, no permalink text -> nothing written. (3) u == lurl same as today. Plus end-to-end through run.build(). Mutation: remove the _proof branch in proof.py -> test 1 must fail.
