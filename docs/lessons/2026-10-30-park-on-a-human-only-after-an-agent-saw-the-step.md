# 2026-10-30: park on a human only after an agent saw the live verify step

- Four of nine Your turn rows were wrong when Mike worked them: ezlocal (email verify, row said sms), ibegin (vendor sends no verify), showmelocal ($6.99 paid claim), com-yellowpages (redirects to bestyell.com). Each was parked from a playbook note or a guess, never from the live step.
- The rule now lives in code (`job/your_turn_gate.py`, called by `record_transition` for any `verify_type`): an observation of type, screenshot, price and date within 7 days is required, and paid, dead/redirect and email-verifiable Directories are refused before any write. Prose rules did not stop this; a refusal does.
- A gate that only looks at the row's own fields repeats the mistake. It compares the OBSERVED type with the parked type and reads the Directory DB dead/cost flags, failing closed if that read fails.
- Adding a gate to a shared writer breaks every existing test that parks a row: give each a valid observation (tests/yt_obs.py) rather than weakening the gate.
- Cloudflare blocked the agent's public readbacks (yellowpages, dexknows, ezlocal) on 10/30. Do not claim a readback you could not make; leave the row on Your turn and say so.
