# Lesson: bind the control to the tool, and test against the real command line

Round 1 of t_45fe02d4 named the tenant's browser in the prompt and checked the port holder's `--user-data-dir`. Review found three ways that still failed:

1. The agent's browser tools start their own Chrome unless `BROWSER_CDP_URL` is in the child's env. A prompt line cannot steer a tool that has no such switch. Rule: when a run must use one resource, put it in the process env or argv of the thing that uses it, then test that env. The prompt is the second line, not the first.
2. The parser was written from the shape I expected (`--user-data-dir="path"`), and the fixtures matched the parser. The live main process has the quote before the flag and a space in the path. Rule: copy fixtures from the live command line (`Get-CimInstance`/`list_procs`), including the ugly ones, and add a mutation that reverts the parser.
3. `os.path.expandvars("%X%")` and `normcase` do nothing on Linux, so a Windows-only comparison passed locally and died in CI. Rule: fold slashes and case explicitly, read env vars with `os.environ`, and set the env the test depends on inside the test.

Also: a shared port is shared state. Take the owner's lease (and refresh it) before using it, refuse when someone else holds it, and never release or close what a newer holder now owns.
