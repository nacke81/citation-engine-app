# Lesson: a client-facing count must be the same rule as the claim behind it (t_9d36198a)

The portal summary counted every row whose state was "live". The scan maps "found" to "live", so three found-but-unproven rows (google.com GBP, maps.apple.com, n49.com) lifted 23 proofed rows to 26. The contract basis is live + proof (GBP excepted), so the summary overclaimed by two.

Rule: derive the number a client sees from the same predicate the contract states, at the one place the number is written, and pin it with a fixture shaped like the prod bug (26 -> 24). When a count rule changes, old goldens that assumed "state live counts" must be re-read, not just re-greened: here one test fixture (R3) lacked proof and was updated on purpose.

Review round 1 corrected the first fix: the portal page counts `state == "live"` rows and drops `summary` and any extra flag (normalize-citations.ts, CitationsBlock.tsx), so a recounted summary changed nothing the client sees. Read the consumer before choosing where to apply a rule, and assert on the field the consumer reads. Also: a test that passes locally by reading prod is not a test; make external sources injectable.
