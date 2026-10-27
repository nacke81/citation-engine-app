# Lesson 2026-10-27: test a classification rule on real row shapes, through every write path

A fixture built from a card's counts proved the counts, not the rule. The first nap-fix rule ("a listing exists") passed a fixture that was shaped to give 5 / 26, then gave 21 / 10 on the real queue, because paid-tier and wall rows carry evidence URLs too. The weekly write also overlaid only one of the queue's three lists, so most rows and every stored NAP read never reached the snapshot.

Rules:
- Define a class by the observation that proves it (a NAP read came back wrong), not by a nearby signal (a URL exists).
- Keep a scrubbed copy of real row shapes as a golden fixture, and assert the same class on every write path (finalize only, partial overlay, full overlay).
- A writer test must put rows in every list the queue has, and read the result back through the fake portal.
