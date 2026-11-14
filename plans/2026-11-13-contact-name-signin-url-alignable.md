# Plan: {contact_name} placeholder, park --signin-url, alignable verify seed (t_9de1c978)

Cites lesson `docs/lessons/2026-11-13-one-source-for-the-steps.md` (latest): steps carry placeholders only, the validator needs a deliberate allowed set, and each permission is tested both ways. A new placeholder is a new tenant value, so it must be added to the validator AND the filler together, and a value with no source must stop the run, not fill blank.

Part A (done before this PR, no code): migration 017 applied to the Directory DB, thumbtack verify playbook set. Evidence is on the card.

## Build
1. `job/playbook.py`: add `contact_name` to `PLACEHOLDERS` (validator and renderer share it) and the docstring.
2. `job/verify_send.py` `tenant_values`: fill `contact_name` from the identity file's `contact` key when present, else from a small per-tenant constant `CONTACT_NAME` (NM only, built from split strings like `EXPECTED_LOGIN` so the repo leak check stays green). SCC has no value: a playbook that uses `{contact_name}` for SCC fails closed (`render` already refuses a placeholder with no value).
3. `park --signin-url <https url>`: `transitions.py` CLI + `record_transition(signin_url=)` -> `verify_allowlist.auto_add(signin_url=)`. A new auto entry uses it instead of `https://<domain>/`. The URL must be https, no userinfo, no spaces, and its host must be the Directory domain or a subdomain of it (refuse otherwise before any write). An existing LOCAL auto entry whose signin_url is still the bare root is upgraded to the given URL; a repo entry's signin_url is never replaced. Omitted flag = today's behaviour.
4. `config/playbooks/alignable.com.verify.json`: five steps from the card, `send_is_signup` true, placeholders `{login_email}` `{contact_name}` `{phone}` only.

## Tests (offline, in the existing CI files)
- `tests/playbook_test.py`: alignable seed validates and `send_is_signup` is true; `{contact_name}` accepted by the validator, still refused when unknown placeholders are used; `tenant_values` returns the NM contact and none for SCC; render of the alignable seed with NM values has no `{` left; render for SCC fails closed; mutation: drop `contact_name` from `PLACEHOLDERS` and the seed is refused.
- `tests/verify_allowlist_test.py`: auto_add with a signin_url writes it; without it writes the bare root; foreign-host, http, userinfo URLs refused with no write; repo entry signin_url untouched; local bare-root upgraded. Park CLI path passes the flag through; omitted flag unchanged. Mutation: ignore the flag, the test fails.
- Existing fence/tenant-lock tests unchanged and run.

## Out of scope
No change to the fence or tenant lock. No send clicked. Applying the alignable playbook (`playbook.py set`) happens after merge (card Part B tail); `alignable.com` is not yet in `ce_directories`, so the `set` needs the directory row added through the normal path first.
