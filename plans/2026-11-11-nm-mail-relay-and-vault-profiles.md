# Plan 2026-11-11: NM vault-write profile + listings@nackemedia.com mail relay (t_04751f6a)

Cites lesson `docs/lessons/2026-11-11-scope-a-read-only-where-the-scope-can-see.md` (latest): a read scope must be enforced where the scope can see it, and tested with the out-of-scope item placed outside. Here the scope is "only mail to listings@nackemedia.com": it is enforced twice (the query is pinned and refused if changed; every fetched message's own To/Delivered-To headers are re-checked, so a message that is not addressed to listings@ is dropped even if Gmail returned it).

## 1. Vault write profile (`mkpayload.js`, citation-submitter skill, not in this repo)
- `--client scc|nm` (default `scc`) plus overrides `--org`, `--collection`, `--username`. Defaults unchanged (SCC org/collection/username), so every existing SCC call yields the identical payload.
- NM profile: org `Nacke Media`, collection `Citations`, username `listings@nackemedia.com`. Item name stays the caller's positional arg (`NM - <domain>`); `--client nm` also validates the prefix `NM - ` and scc validates nothing (unchanged).
- Tests (node:test): SCC payload byte-identical to old behaviour; NM payload; override flags; unknown client refused; CLI dry run writes only the payload file (no vault call). No live write.

## 2. Relay
- `job/nm_listings_relay.py` (installed copy on the nacke-media profile `scripts/`). Query constant `to:listings@nackemedia.com newer_than:2d`, account `mike@nackemedia.com`. `--query` accepted only if it starts with `to:listings@nackemedia.com` and carries no `OR`, `-`, `{}`, parentheses or `in:`/`from:` broadening; anything else exits 2 without calling gog.
- Only read verbs of gog (`gmail search`, `gmail thread get`) are ever built; a test asserts no argv contains `send`, `forward`, `drafts`, `modify`, `label`.
- Per message: skip DRAFT/SENT, require listings@nackemedia.com in To/Delivered-To/X-Original-To/Envelope-To/Cc, extract links and codes with `mail_scan` helpers, append `{id, from, subject, received, links, codes}` to `%LOCALAPPDATA%/citation-engine/mail/nm-listings.jsonl`, deduped by id. `--dry` prints id/from/subject/counts only (never links/codes) and writes nothing.
- `mail_scan.py --mailbox nm-relay` reads that file through the same message-dict shape as `read_messages`, so `--presence` / `--reset-link` / approval flows work. Missing file = empty list, not an error.

## Tests (failing first)
`tests/nm_relay_test.py`: query guard (6 bad queries refused, gog never called), only-listings filter with a decoy message to another address, read-only argv, dedupe, jsonl shape, dry prints no link/code, reader feeds `find_reset`.
CI line added to the workflow next to the other Python tests.

## Not
No cron created, no live vault write, no send/forward, no queue write, no portal/Directory action.
