# Lesson: a prompt line is a promise; check the code path makes it true (t_45fe02d4)

Prompt step 1 said "use the one browser session this run reserved". Only the Cylex script path reserved a browser; the agent path launched `hermes ... --oneshot` and nothing else. The agent opened a fresh browser, hit reCAPTCHA on Alignable, and the playbook (correctly) stopped. The signed-in session lived in a profile no file named.

Rules:
- When a prompt says "the X this run reserved", grep for the code that reserves X on THAT path. If none, either create it or stop saying it.
- Put a tenant's browser (profile + port) in one table; prompt text, Chrome start and the port check all read that table. A swapped pair (NM given the SCC profile) is a tenant-lock break, so the test needs a mutation that swaps it.
- A listening port is not proof of whose browser it is. Compare the listener's `--user-data-dir` to the tenant's profile and refuse on any mismatch or unreadable command line. Reuse a match and leave it running; close only a Chrome this run started, and keep the profile.
- A test that passes a client id where a tenant tuple belongs only worked while nothing read the tuple. A new lookup on `tenant[0]` exposed it; fix the test input, do not loosen the lookup.
