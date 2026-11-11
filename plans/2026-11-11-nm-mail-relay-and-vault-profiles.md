# Plan 2026-11-11: NM vault-write profile + listings mail relay reader (t_04751f6a)

Cites lesson `docs/lessons/2026-11-11-scope-a-read-only-where-the-scope-can-see.md` (latest): a read scope must be enforced where the scope can see it, and tested with the out-of-scope item placed outside. The relay's scope (only mail to the NM listings alias) is enforced twice: the query is pinned and refused if changed, and every fetched message's own recipient headers are re-checked.

## Repo rule found in CI
`tests/leak_check.py` forbids the real NM identity words anywhere in this repo (public Pages repo). So the relay script and its test live on the NM seat profile (`scripts/nm_listings_relay.py`, `scripts/tests/`), exactly where the card puts them. This repo carries only the generic reader. `vendor/` is skipped by the leak check, so the vendored vault helper may name the NM org.

## 1. Vault write profile (`mkpayload.js`, citation-submitter skill dir; vendored here for CI)
- `--client scc|nm` (default `scc`) plus `--org`, `--collection`, `--username` overrides, and `--dry-run` (redacted payload, writes nothing). No flags = byte-identical SCC payload.
- NM: org "NM", collection `Citations`, username = NM listings alias, item name must start `NM - `.
- Tests: SCC default key-for-key unchanged, NM payload, overrides, prefix refusal, bad flags, CLI dry-run for both profiles writes no file. No live vault write.

## 2. Reader in the engine (`job/mail_scan.py`)
- `--mailbox nm-relay`: every mode reads the relay JSONL file (`%LOCALAPPDATA%/citation-engine/mail/nm-listings.jsonl`, or `NM_RELAY_FILE`) instead of IMAP. Missing file = no mail.
- New `--verify-link --directory D`: newest email-verification mail from D, prints link and code to the terminal only (same posture as `--reset-link`), exit 0 found / 1 none / 2 unreadable.
- Tests `tests/nm_relay_reader_test.py`; CI step added.

## 3. Relay (profile script, not in this repo)
Query pinned (`to:` NM listings alias + optional `newer_than:`/`older_than:` only), account mike@, only `gmail search` and `gmail thread get` can be built, recipient re-check, DRAFT/SENT skipped, dedupe by id, `--dry` prints counts only. Test file: 34 checks, fake gog.

## Not
No cron created, no live vault write, no send/forward, no queue write, no portal/Directory action.
