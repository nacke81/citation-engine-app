# 2026-11-04: every path that parks a row has to name its reason, and a dry run has to prove it

- PR #75 added reason_code but only the `transitions.py` flag carried it. Five other paths park or print a park command (buildrows, walls try 3, recheck cap, captcha_route, build_runner) and none named a code, so those rows fell to "Other".
- Find the paths by grepping for the state string (`needs-human`), not by listing the known callers.
- A dry run that does not echo a field cannot prove the field. A bad value also has to be refused before the first write; the sink used to fail after the queue file was already written.
- Paths that write the queue file directly store the code on the history entry at park time. They do not call the Directory sink, and the weekly job must stay code-free (clearing lives in sync_transition only), so carrying the code to ce_directory_status is a backfill decision.
