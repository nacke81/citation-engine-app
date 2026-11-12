# Lesson: an agent step gets a narrow helper and a clock it cannot reset (t_218b03ef)

Verify Now now hands the send step to an LLM oneshot for any Directory without a script. The oneshot can hang, wander, or end without reporting. Three rules held the build together:

1. The agent calls one small CLI (`job/verify_step.py sent|code|result`), never an RPC. The helper re-reads the request, runs the same `fence()`, and owns the state moves. So the agent cannot skip a step, move a row to live, or see the service key, and a test can drive the whole flow with plain function calls.
2. The run that launched the agent owns its clocks, measured from the portal row, not from the agent's say-so: 25 min with no `sent` call kills the whole process tree (`taskkill /T`; killing only the parent leaves children), 35 min after `sent` kills it, and when the agent exits with the row still open the run finishes it with an allowlisted code. Test it with a fake runner that hangs and a virtual clock.
3. An empty read is a miss, not a verdict. `superseded` means a row that is PRESENT and no longer waiting. Treating a missing row as superseded would let a flaky read silently drop a client's code.

Also: put "which Directory, which channel, which send mode" in a data file the operating seat edits, and make "not in the file" the fail-closed default with a read-only `--check` that lists the gap. A hard-coded tuple turns every new Directory into a code change.

4. A fake oneshot cannot show the seam to the real tool that runs the helper. Read the host tool limits (Hermes terminal: 180 s default, 600 s foreground max, longer goes to background) and bound every blocking helper call below them: `code --wait-s` (max 540) exits 6 = "no code yet, run again", and the 30 min limit is anchored to the portal row (`code_sent_at`), not the call start, so repeats cannot stretch it. Check expiry before consume (consume deletes, so a late or killed call must not take a code it cannot deliver). Give agents absolute interpreter and helper paths and launch them with an explicit cwd: the bridge cwd is not a contract.
