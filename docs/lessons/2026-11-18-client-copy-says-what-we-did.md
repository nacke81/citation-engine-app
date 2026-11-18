# Lesson: client copy states only what we did, and a mutant must name the line it breaks (t_d9ed56f5)

A listing we found already live is news ("confirmed live"), not work ("added", "built", "submitted"). The title is a contract with the client, so it gets its own test plus a mutant that rewrites it to "added" and must fail.

Rule: when a new client row reuses the one writer (`P.write_deliverables`), build it in one function that returns None unless every fact the sentence needs is literally true (state live, build_action existing, `proof_nap_match is True`). A mutant that drops `deliverable_row` from the builder is NOT caught by the row check, because the transport helper re-stamps `approved_at`; that is defence in depth working. Mutate the call site instead (post around the writer) and the path/guard checks fail as they should.

Counts: before adding a row type, name every consumer of the count. Here the engine's `existing` bucket already sat outside newLive/claimed/fixed; a before/after test pinned it so a later change to the bucket fails loudly.
