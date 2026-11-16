# Lesson: a gate that fails closed must fail only on the refusal, not on every scary word (t_4ee21e60 rework)

Evidence: review of PR #122 found `sent` finished the request failed on ordinary help text of a SUCCESSFUL code page ("Didn't receive it? Try again", "Invalid code will lock the account..."), so a real text reached the phone while the portal said failed and a retry sent a second code. The call path also passed "We called your phone" with no code field. Two vault-check exits had no test, so two source mutations survived every suite.

Rules:
- A terminal state (failed) needs a narrow trigger: the phrases that mean the Directory refused the send. A broader error word only REFUSES the record step (nothing written, state unchanged) and tells the agent how to proceed. Wide net = refuse; narrow net = finish.
- Landed evidence names the thing the next step needs (a code), on every channel. "We called you" is a click report, not evidence.
- Every fail-closed exit gets its own test and a named mutation. Write the mutation of the line (replace one source line, rerun the suite) and require the suite to catch it; a gate nobody mutated is a guess.
