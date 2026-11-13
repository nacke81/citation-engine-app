# Lesson: steps the agent runs and steps a human reviews must be one record, with placeholders (t_413687a7)

The first design stored the per-directory steps as `agent_steps` in the local allowlist JSON. That is a second copy: Mike reviews one thing in the app, the agent runs another. Nate's scope change moved them into one Directory DB table the app shows and the agent reads.

Rules that came out of it:
- Store steps with placeholders (`{login_email}`, `{phone}`, `{vault_item}`), never tenant values, so the same row is reviewable and safe to display. Validate at write time (emails, phones, 6+ digit runs, `password:` assignments) and again at render time; a placeholder with no value stops the run before the agent starts.
- A validator needs a deliberate hole where real data looks like a secret: Thumbtack's `category_pk` is an 18-digit catalog id in a url. Exempt the url field from the digit rule, keep every other url check, and test that the exemption is only the url.
- A permission carve-out ("the send IS the signup") must be one flag on the stored row, read at run time, default false, and tested in both directions plus a mutation that ignores the flag.
- A vault resolver widened to a new tenant must filter by tenant BEFORE ranking. A refusal test needs a mutation showing the wrong tenant's item is returned once the filter is gone.
- A path-heavy test checkout can trip a "no 6-digit run" assertion (`t_413687a7` in the helper path). Strip helper lines before scanning, do not loosen the rule.
