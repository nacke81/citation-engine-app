# Pin the query and re-check the message: a mailbox scope needs two locks

Plan `plans/2026-11-11-nm-mail-relay-and-vault-profiles.md` cites the earlier lesson `2026-11-11-scope-a-read-only-where-the-scope-can-see.md`.

A relay that reads one alias of a shared inbox must not trust the search query alone. The query is pinned and the script refuses any other (including broadening tokens like OR, negation, braces, `in:`), and every fetched message is re-checked against its own recipient headers, so a wrong hit is dropped even if Gmail returned it. Tests pin both locks separately with a decoy message addressed to someone else, and assert the only gog verbs ever built are search and thread get. A zero-count dry run proves nothing about the filter; the real-mail dry run (10 hits in 30 days, all to listings@) and the decoy test together do. Also: tie-break fixtures on distinct timestamps, or "newest" tests pass by accident of uid order.

Second note: the vault-write helper lived only in a profile skill dir with no repo and no CI. A vendored copy plus a CI step is how a tool like that gets a test gate; the live copy and the vendored copy must be re-synced by hand.
