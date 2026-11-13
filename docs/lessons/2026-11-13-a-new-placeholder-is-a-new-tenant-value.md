# Lesson: a new placeholder is a new tenant value; give it a source and a refusal (t_9de1c978)

Alignable needs the contact person's name on a signup step. Adding `{contact_name}` to a playbook looks like one word, but it touches three places that must agree: the validator list (`PLACEHOLDERS`), the filler (`tenant_values`), and the tenant that has no value.

Rules:
- Add a placeholder to the validator and the filler in the same change, and test the seed against both. A mutation that drops it from the validator list proves the list is what lets the seed in.
- Say where each tenant's value comes from. NM has one; SCC has none. A tenant with no value must fail closed (render refuses the unfilled placeholder), never fill a guess or a blank. Test both tenants.
- The repo leak check bans tenant identity words, so a value that has no identity-file key lives as a split-string constant, the same pattern as `EXPECTED_LOGIN`. Prefer the identity file key when it exists.
- A CLI flag that writes a URL into a runtime allowlist (`park --signin-url`) must refuse before any write: https only, no login in the URL, host equal to the Directory's own domain or a subdomain (test the look-alike suffix `notdomain.com`). A refusal test needs a mutation showing a foreign host is written once the check is removed.
- An auto-written default (the bare domain root) is data that will be wrong. Let a later explicit value upgrade a default, but never let a later value replace a real one.
- Applying a table migration is not the same as editing `schema.sql`: `db/apply.py` runs only `schema.sql`. State which file was applied and read the table back.
