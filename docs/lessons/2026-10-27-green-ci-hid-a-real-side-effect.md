# Lesson 2026-10-27: green CI hid a test that made real Kanban cards

Card t_20ccb0b4. Two test cases called a function that shells out to the real `hermes` CLI, because the fake runner was installed later in the file. CI has no hermes, so the call failed silently and stayed green; a local run created real cards.

- Install the fake for any external side effect at the top of the test, as a tripwire that records calls, not halfway down.
- Stub the lower layer too (`subprocess.run`), so a path that skips the injection point is still caught.
- Give side-effecting code an env kill switch (`CE_NO_CARDS=1`) and set it in the test.
- A silent-failure path ("CARD FAILED") makes CI green by accident. Prove no side effect against the real system after a local run.
