# Lesson: a second business must not borrow the first one's proof (t_62f64298)

The v3 Spike pushed NM through the SCC proof path for the first time. Four things were wrong that no SCC-only test could show:

- `mirror_proof` copies a complete ce_directory_status Proof into a live queue row that has none, matched by directory name. It read `biz=SCC` only, so four live NM rows (n49, brownbook, manta, cylex) had been given the SCC proof for the same domain: a Senior Care address and phone quoted on an NM row. Those rows looked proven to every guard, so the proof backfill refused to touch them.
- `record_proof` hard-coded the business and the SCC queue path, so an NM row could never get proof at all.
- NM rows were moved live by a queue-only writer, so their status rows were not `queue_state=live`, and the ledger counts only live rows with Proof. A proof with no live status row counts as nothing.
- The comparator needed a street. NM's record lists its street only if a form requires it, so a listing with city, state and the right phone could never be a match.

Rules:
- A reader or writer of a shared table takes the business as an argument. Matching by directory name alone is a cross-business join. Test it with the same domain on two businesses.
- A guard that says "this row has a complete proof" must check whose proof it is. Read the proof text on one real row of the second business before trusting the count.
- When a rule differs per business, put the difference in the business's data (a key on its canonical record), never in a branch on its id. The test then needs a control: a canonical without the key behaves as before.
- A count that the ledger defines (live with Proof) is the thing to check after a write, by a read-only query on the real table, not the writer's return value.
- A guard that counts a banned name in the repo counts every file, including plans, lessons and tests. Spell the names from pieces in any new file.
