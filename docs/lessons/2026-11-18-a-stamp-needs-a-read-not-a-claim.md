# Lesson: a stage stamp needs a page read, and a hang needs a name (t_761c9558)

Three Thumbtack runs left no screenshot, two showed `signed_in_at` while the session was signed out, and the third hung on "Loading" and was recorded as a generic send failure. All three trace to one habit: the scoreboard trusted what the agent said it did (arm, "I am signed in", "I clicked") instead of what the page showed.

Rule: every stamp that means "the Directory was in state X" is written by the helper after it reads the page itself (read-only CDP), and the page is saved (screenshot + redacted text) at the moment of the decision. An unreadable page decides nothing and stamps nothing. A wait that ends with no answer (Loading, no code boxes) gets its own reason (`send_unconfirmed`), never the generic failure, and never a retry of the send. Stops that happen before any send (`session_signed_out`, `captcha`) are marked so the platform's code-request fence does not count them.

Proof: a mock page in each state (signed out, CAPTCHA, signed in, Loading, code box, unreadable) drives the real helper functions; the row's outcome, stamp, `fence_skip` and linked files are asserted, not the log text.
