# Lesson: a reaper must ask the owner's liveness signal, not just read a clock (t_fb7ae698)

`--reap` killed any build_chrome.py tree older than 60 min unless a card lease was fresh. A lease goes stale between steps, so a live batch on another port (9444 next to 9333) looked abandoned and was killed with its Chrome.

Rule: before a cleanup actor kills something by age, check the thing's own liveness (its Chrome process in the tree, its port answering) and scope the kill to the caller's own lane (`--stop` reaps only `--port`). Count a kill as done only when a re-list shows the root gone; a failed kill is `left`, rc 1.

Test it with two old trees, one live and one dead, and a mutation that removes the alive check; the test must fail.
