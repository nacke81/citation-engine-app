# Lesson: landed evidence must be a state the page shows after the act, never a word the act itself carries (t_6168a061)

Evidence: PR #124 review probed `step_sent` and found "Send verification code" (the button label), "Get verification code" and "We have not sent a code yet" recorded as a landed send, because a bare noun phrase and an un-negated `sent ... code` matched.

Rules:
- Match evidence by a state/context (code field, "code was sent", "enter the code"), not by the noun the controls also use.
- Strip negated clauses before matching; a negation never lands.
- Every sentence of a prompt a gate depends on ("Quote ONLY the code-box text") needs a test that fails when it is deleted.
