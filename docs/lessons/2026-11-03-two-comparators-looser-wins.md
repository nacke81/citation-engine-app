# 2026-11-03: two comparators on one page means the looser one wins

- 11/01 PROOF (name+street+phone) moved nextdoor live on a page RECHECK called nap-incomplete in the same run. A second, looser comparator is a second writer with its own rule.
- Fix by routing the live decision through the one comparator (`recheck.compare` via `read_listing`); the old check stays only as a pre-filter. A test asserts PROOF moves iff RECHECK says match on the same text.
- Tests that stubbed the loose input had to inject a reader; the new tests use real page text shapes (partial NAP, JS shell, wrong zip, hidden banner).
- Demoting through `record_transition` to needs-human does not clear Proof: the queue row's `proof` and the ce_directory_status Proof columns must be cleared separately (done by hand this time; a follow-up could make demotions clear them).
