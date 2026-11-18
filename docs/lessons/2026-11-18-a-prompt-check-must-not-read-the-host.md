# Lesson: a "no digits in the prompt" check must build the prompt from fixture inputs only (t_cd0e943e)

A test failed on one PC and passed in CI. The suspect was a leaked code; the cause was the Python interpreter path embedded in the prompt, which on this host holds a hash with a 6-digit run. Before calling a leak or a test bug, mask the digits and print where the match sits; that told us in one run.

Rule: any value the prompt takes from the host (interpreter path, home dir, repo path) is pinned to a fixture in tests that assert on the prompt's text. Keep the real-value check in its own test. Never loosen the assertion; add a mutation that proves it still fires.
