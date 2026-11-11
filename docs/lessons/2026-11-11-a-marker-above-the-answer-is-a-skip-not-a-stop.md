# A marker above the answer is a skip, not a stop (t_ffa900be)

Context: PR #93 ended a listing's block at every neighbour-section marker. Yelp's "You Might Also Consider" sits above NM's own address, so making it a stop would have cut the address off and turned every Yelp listing into "no street, no phone diff". Page-wide `street`/`old_street` flags also disagreed with the block the fix list reads.

Lessons:
- Before adding a stop marker, look at the saved real page and ask where the answer sits relative to it. Above the answer: skip to a resume marker; below: stop.
- A skip needs a fallback when its resume marker is missing (here: the old behaviour), or one odd page loses data silently. Test the page both with and without the resume marker.
- Every flag that can make `match` true or false must be read from the block the diff reader reads. When a flag comes from prose, the diff step must still emit a diff for it (a not-match without a diff breaks the invariant).
- Apply a scoping change only to the identity that asked for it (NM). Prove the other identity unchanged by diffing its saved-page output against main byte for byte, not by reasoning.
