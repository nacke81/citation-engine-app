# Plan: mail_scan refuses a Directory it cannot see (t_2b13224d)

Cites lesson `docs/lessons/2026-11-17-creds-outside-the-env-need-a-fence.md` (latest at start): a "pass" can come from a path that never looked. Same shape here: "0 mail" came from a scan that could not see the sender.

## Defect (base eb9e1b7)
SCC mode: `_domain_of()` is None for any directory outside `SCAN_DIRECTORIES`; `presence()`/`header_rows()` then count 0 and print `<d> | 0 matching mail(s)`. `find_verify` falls back to the raw directory name instead.

## Change
1. `config/mail_domains.json` = the map (directory, domain, aliases, approval). `SCAN_DIRECTORIES` (the approval-scan set recheck.py and batch17 read) is derived from rows with `approval:true` = exactly the old six; new rows (kentuckyonline.us alias usaonline.us, kentuckyizze.com, sortlist.com, clutch.co) are scan-only, so recheck behavior does not change. Operating seat adds a Directory by editing the file.
2. `_domain_of` (SCC) reads the whole file. `mail_is_from` SCC branch: a From whose single addr-spec host is the domain's alias host counts. The brand / other-Catalog-domain guard is untouched.
3. `_unmapped(dirs)`; presence_main, headers_main, reset_main, verify_main and the approval scan in `_main` print `DIRECTORY NOT MAPPED: <d>` to stderr and return 2 before reading the mailbox or printing any count. `find_verify` uses `_domain_of` (no raw-name fallback). nm-relay open-domain mode unchanged.
4. Tests `tests/mail_scan_unmapped_test.py` (in CI): refuses per mode, alias counted, same-brand other-Catalog From rejected, alias spoof rejected, bad data file fails closed, mutation (restore silent None) detected.
5. Positive control: one read-only `--presence --headers --directory kentuckyizze.com` scan (IMAP EXAMINE/PEEK, creds via the existing env path; nothing printed but headers).
