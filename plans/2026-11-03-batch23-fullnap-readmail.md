# 2026-11-03 Full-NAP guard + readmail link (t_57178c17, rescoped by Nate)

Cites latest lesson: docs/lessons/2026-11-03-two-comparators-looser-wins.md (one comparator decides live; a hole in it is a second looser writer).
Items 1-2 (dot separator, submitted->created-unlisted) are PR #66 (t_3f38d45e); this branch is based on fix/proof-gate-middot.

- recheck.compare: when the street came from the page text, the block must also show the city and the zip (zip may come from the street reader), else an `address` gap (nap-incomplete). State not required in text (real pages omit it); a wrong state/city/zip stays mismatch via the existing path. Structured address path already required city/state/zip.
- readmail: tested copy job/readmail.cjs; undeclared-QP only trusted on soft break or =3D, so activateid=2043.. is byte-exact.
- Tests: tests/recheck_fullnap_test.py (street-only card text must not match; yellowpagecity fixture stays match), tests/readmail_test.cjs. CI steps added.
