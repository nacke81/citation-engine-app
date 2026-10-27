# Lesson 2026-10-27: recount summaries from the rows on every write; never store a total

Card t_f6267312. The SCC snapshot carried scan totals (found 11, couldntCheck 14, checked 11, directoriesChecked 25) written once by the 10/21 scan. Every later write overlaid queue states onto the rows and left the totals alone, so the app said 11 / 0 / 4 / 14 while the rows said 19 live. Neither the app nor the portal was true.

- A total that is written in one place and the rows it counts in another will drift. Recount in the ONE function every writer passes through (`snapshot.finalize`, called by `build_payload` and `overlay_directories`), and have the write's readback compare the summary, not one old field.
- One overloaded state hides two different jobs: a row with a listing and wrong NAP (a person edits it) and a row with no listing (a person builds it). Split in the snapshot, derived from the queue row, and leave the internal state machine alone.
- A null that means "never looked" must become either a result or a null with a reason. Store the NAP read on the queue row (`nap_check`) so the snapshot never guesses, and only a clean match is True and only a shown wrong value is False.
- Build the golden fixture from the counts the human saw on prod, then add a property test that the summary equals an independent recount, so the next frozen field fails CI rather than a client screen.
- Runner rules (no heredocs, no `python -c`): edits to CRLF files go through a throwaway script file that normalizes line endings; multi-line patch matching fails on CRLF.
