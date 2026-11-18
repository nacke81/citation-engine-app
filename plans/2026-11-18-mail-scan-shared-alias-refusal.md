# Plan: mail_scan refuses a shared alias across Directories + 3 test gaps + G2 fixture queue (t_19510826)

Cites lesson `docs/lessons/2026-11-18-two-sources-one-page-must-agree.md` (latest at start): a new source must not override what the data itself contradicts. Here: one alias host on two Directory rows is a contradiction, so refuse rather than guess.

## Change
1. `load_mail_domains()` raises ValueError when one alias host, or a host under/over it (a.b.c vs b.c), is listed on two different Directory rows; the message names both rows.
2. Tests in `tests/mail_scan_unmapped_test.py` (the existing 49 stay): duplicate alias raises + names both; From `<a@usaonline.us> (b@evil.io)` rejected on kentuckyonline.us; `find_verify("kentuckyonline.com", msgs)` is None; queue row `"yahoo.com (local.yahoo.com)"` does not self-map. Each paired with a mutation run that fails it.
3. G2 (t_2b13224d scope add): `tests/nm_tool_gaps_test.py` G2 run uses a temp `--queue` fixture and `unmapped-example.invalid`; `tests/batch21_test.py` mail_scan.main calls pass a temp `--queue`. No test reads the live queue.
