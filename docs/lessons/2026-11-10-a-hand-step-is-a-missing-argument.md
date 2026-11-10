# Lesson: a hand step in a playbook is a missing argument or a missing writer (t_bc10b2d3)

Cite: `plans/2026-11-10-pagekit-v3-page-action.md`.

The findcarez signup needed three hand steps: call the CLI directly because pagekit had no pageAction, override grecaptcha.execute in the page, and write the solve log by hand. Each was a parameter or a write that the helper did not own.
Rule: when a playbook says "do X by hand because the helper cannot", fix the helper, and route the hand path (CLI wrapper) through the same function that logs, so the per-row cap and the log cannot diverge.
Test the injected JS where it runs: the page-evaluate script executed in node against a stub DOM catches what a fake page returning canned counts never will. Mutation checks (drop the extra, break the execute override) both fail the test.
