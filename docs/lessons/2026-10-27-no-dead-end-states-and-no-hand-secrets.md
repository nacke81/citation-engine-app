# Lesson 2026-10-27: a terminal state needs a logged way out, and a secret needs one code path

Card t_d2f75685 (batch 16 problems). Three engine gaps cost a whole batch (0 new live):

- `rejected` was terminal with no edge back, so a Directory that rejected a fixable listing (acompio: "Insufficient description") left the row stuck. A terminal state is fine only if a deliberate, logged exit exists: `rejected -> queued` needs `--reason`, writes `requeue` + `reason` to history, and never clears the hard-block count.
- The IMAP password moved to the vault but the code still read only the env, so each batch wrapped `mail_scan.py` by hand. When a secret moves, change the ONE function every caller goes through (`hotfrog.mail_env`) and test both outcomes: env empty + vault readable, env empty + vault missing (a loud "MAILBOX NOT READ", never "no mail").
- Names typed by hand drift (`SCC - citylocalpro` vs `.com`). Resolve once, print the name only, and let the fill helper take the resolved name.

Also: a status read that takes the first word it finds in page order is wrong when two words show; the spec list order is the precedence. A field the Directory judges on (description) must be validated in code before any form is touched, and never invented in code.

Test habit: block `subprocess.run`, `urlopen` and `imaplib` before importing the modules under test, so a missing fake fails loudly (see 2026-10-27-green-ci-hid-a-real-side-effect.md).
