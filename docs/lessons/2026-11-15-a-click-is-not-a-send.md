# Lesson: a click is not a send, and the slowest start step belongs beside the start, not before it (t_4ee21e60)

Evidence: Alignable 53b9cd5e reported `sent` after a click, but the page said "The number entered is not a mobile phone." Mike had a code box and no text coming. Thumbtack 075091fb stopped on a phone compare the page could not satisfy. Both clicks waited 2.5 minutes before the agent existed, because two serial Bitwarden reads (59 s + 72 s, each a login, unlock and sync) ran first.

Rules:
- Record an irreversible step as done only on evidence read AFTER it (the page shows the code field and no error), passed in as an argument that the recorder refuses to run without. The agent's report of its own click is not evidence. An error on the page takes the failure path and keeps the page text.
- A check that could be dropped by a prompt rule must be a gate in code: the agent starts at once, the identity check runs beside it, and `arm` will not go until the check wrote its marker. A failed check kills the agent and ends the request.
- Time the start-up steps one by one before tuning the poll interval. Here the poll cost 15-60 s, the two vault reads cost 131 s, and one of them was a strict subset of the other (same `readItem`).
- A playbook flag that relaxes a check carries its evidence note and is validated like any other value (no digits, no phone). Keep the strict check as the default.
- A scheduler tick can hold a loop (passes every 15 s inside a 60 s tick with IgnoreNew) for a latency cut with no new scheduled task.
