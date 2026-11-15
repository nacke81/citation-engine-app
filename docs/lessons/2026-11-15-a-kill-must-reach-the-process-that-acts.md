# Lesson: a kill must reach the process that acts, and the last step before a side effect must re-check the request (t_c6eee3cb)

`hermes chat --oneshot` is only a client of the profile's gateway. The bridge killed the client; the gateway turn kept running and clicked a real send (a real SMS) after the request had been swept. The same indirection dropped the child env (BROWSER_CDP_URL, TERMINAL_CWD): the gateway forwards a client env name only when the profile lists it.

Rules:
- Before relying on a kill, find which process performs the action. If a daemon does, cancel its session (interrupt + close); ending the client proves nothing. Test with a fake daemon that keeps ticking after the client dies, plus a control run where the cancel is disabled and the leak shows.
- The irreversible step (send) gets its own fence run immediately before it, reading the live request. Do not rely on earlier start-up checks or on a kill landing in time.
- A sweep that closes work by wall clock will close live work. Sweep on silence (a heartbeat the worker's own helper calls write), with a hard cap sized from a measured run.
- If the side effect happened anyway, record it: reopen the swept row only on strict conditions (recent, no newer request, fence ok) and log it, so the human gets the code the text carried.
- Give the agent every identifier it needs for a lookup (vault organization, collection, item) and forbid create/edit in the same sentence; an agent that cannot find something will otherwise create it.
- A test's failure detail must never print an env or a command's kwargs: print a count.

Round 2 addendum: an env var set on a client is not a setting on the server that acts. The gateway's browser tools read the CDP URL from the profile's live override (`browser.manage connect`), so the fix is an RPC to that process, checked on its reply, not a config edit or a child env. And a lock keyed per tenant does not protect a resource that is per profile: key the lock to the resource.
