# Lesson: a fixture where two stages tie cannot tell them apart (t_e49457af)

The scoreboard summary computed click-to-send from `requested_at` to `code_sent_at`. A mutation that swapped in `send_clicked_at` survived the first suite, because every fixture row had `send_clicked_at == code_sent_at`. The test passed for the right and the wrong column alike.

Rule: when a report derives a number from one of several close columns, give each column a distinct value in the fixture, then run one mutation per column. A surviving mutation means the fixture, not the code, is the gap. The same card also stamps each stage at the actor that did the work (bridge, send run, helper) instead of rebuilding times from logs, so a mutation that drops one stamp changes a visible column.
