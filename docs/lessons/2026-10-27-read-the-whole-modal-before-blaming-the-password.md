# Lesson 2026-10-27: read the whole modal before blaming the credentials

Card t_2d15878c (batch 19 problems). businessyab's login modal opens on the SIGN UP tab; the log-in inputs are hidden until the "Log in" tab is clicked. The batch 18 spec typed into the first visible email/password pair, which was the sign-up form, so "the vault credentials were rejected" was at least partly our selector. bbb, in contrast, really said "Email and password do not match".

- List every input in a modal with its visibility (and the tab block it sits in) before scoping a selector. Two forms in one modal is normal.
- A failed login step must save the modal HTML (values stripped), not just a screenshot, so wrong password / no account / wrong form can be told apart on the next run.
- A "dry run" flag that blocks every write also blocks the bookkeeping that keeps a batch from repeating itself. Keep bookkeeping (backoff dates) behind its own flag (`--backoff-only`) instead of folding it into `--write`.
