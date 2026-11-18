# A zero is only a fact if the scan could have seen the thing

`mail_scan` printed `0 matching mail(s)` for a Directory whose senders it had no domain for. A submitter wrote "0 mail since 11/10" as fact; the scan never looked.

Rule: any counter keyed by a lookup must separate "looked, found none" from "cannot look". Resolve the key first; if it does not resolve, refuse (nonzero, named on stderr) before any count is printed. Pin it with a mutation test that restores the silent path and watches the test fail, and move the lookup table to data so the next Directory is a one-line edit, not a code change.

Corollary: an existing test that asserted the old zero (`nm_tool_gaps_test` G2) was encoding the defect; read tests that assert an empty result as claims, not as facts.
