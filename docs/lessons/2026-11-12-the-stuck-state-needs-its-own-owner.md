# Lesson: a state that only the happy path leaves needs a second owner (t_0d601426)

Verify Now moves a request requested -> starting -> code_sent -> done. The send run is the only thing that moves it on from `starting`, and the send run can die (Chrome crash, vault down, box off). A row would then sit in `starting` forever and the client would wait on a button that never answers.

Rule: for every intermediate state, name who leaves it when the normal actor is gone, and give that second owner a clock it trusts (here the sweeper, reading `requested_at`, 10 minutes, and a Kanban card keyed `verify-now:<id>` so a retry never doubles it). Test it by making the finish call fail and running the sweeper twice: one card, not two.

Related rules this build held:
- One decision function (`verify_bridge.fence`) is called by both the bridge and the send run, so they cannot disagree about who may send.
- A secret that passes through a variable (the code) is kept out of every exception: catch, map to an allowlisted reason, re-raise `from None`. The leak test feeds a fake code through each failure path and greps stdout, stderr, log files and portal bodies; a mutation that logs the exception text fails it.
