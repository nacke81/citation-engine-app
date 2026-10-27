# Lesson 2026-10-27: a spec that was never seen on the live page is a guess

Card t_962161f4 (batch 18 problems). Both owner-read specs written in batch 17 passed fixture tests and failed on the first real run: bbb has no sign-in form on its home page (the header button opens a modal that links to /account/login), and businessyab has no "Sign in" at all (its header says "Log in"). The fixture was written from the same guess as the spec, so it agreed with it.

- Open the real page in the build Chrome and list the controls and inputs BEFORE writing the spec. Go straight to a login URL when one exists; a modal link is not a step to script.
- Copy the DOM shape seen live into the test (the hidden modal tab vs the visible header control), so the test fails for the wrong selector.
- A dry run only looks the vault item up. It proves the form is found, not that sign-in works: say which of the two a run proved.
- A same-state "nothing written" rule on a verdict that repeats every batch is a cost; give the verdict a retry date instead.
