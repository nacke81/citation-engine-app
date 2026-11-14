# Plan: NM tool gaps - mail_scan presence on nm-relay, recheck on the NM queue (t_5b3b4a3f)

Cites lesson `docs/lessons/2026-11-13-the-writer-is-the-process-with-the-key.md` (latest): a tool must act as the identity that owns the data it touches. Here: recheck judged the NM queue against the SCC identity, and mail_scan judged NM mail against an SCC-only directory list.

Found (t_a6d3218c): (1) `mail_scan --mailbox nm-relay --presence --directory n49.com` says 0 mails although the relay file holds n49 (11/14) and techbehemoths mail. Cause: `SCAN_DIRECTORIES` knows only the SCC no-account directories, so `presence/find_reset` get domain None. The relay reader itself works. (2) `recheck()` compares the queue canonical phone to `IDENT.BIZ.SCC` and refuses NM; `record("SCC", ...)` and the search/bbb helpers are also SCC-hardwired.

Scope (job/mail_scan.py, job/recheck.py, tests, CI, lesson):
1. mail_scan: `_domain_of(directory)` = SCAN_DIRECTORIES entry; only when `--mailbox nm-relay` is set (module flag), an unlisted dotted directory name falls back to itself (matched by from domain / link host, as today). SCC (listings) behaviour is byte-identical: unlisted still yields no domain. Used by find_approval, find_reset, find_verify, presence, header_rows.
2. recheck: `_biz_of(row)` (NM for `nm-` rows, else SCC) and `queue_biz(q)` (all NM -> NM, none -> SCC, mixed -> QueueError). Phone gate compares to that client's identity phones; mismatch still refuses. record(...) calls and bbb/search/resolve helpers take the row's biz. CLI mail scanner name follows the queue's client.
Tests (offline): relay fixture with n49 + techbehemoths mail -> presence yes; same fixture via default mailbox -> still 0 (SCC unchanged); NM queue with NM identity runs; NM queue with SCC-phone canonical refused; SCC queue unchanged; mixed refused; record gets "NM". Mutation check on both.
No network, no portal, no prod writes.
