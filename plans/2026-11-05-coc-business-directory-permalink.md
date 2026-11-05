# Plan: chamberofcommerce /business-directory/ permalinks (t_01116bb8)

Cites docs/lessons/2026-11-04-every-park-path-names-its-own-reason.md: grep for every copy of the shape, not just the named one. The shape lives in job/listing.py PERMALINK and job/permalink.py LISTING_SHAPES.

- Widen both patterns to `^/(united-states/[^?]*|business-directory/[a-z-]+/[a-z-]+/[^?]*)/\d+-` (old form kept).
- Tests in tests/permalink_test.py (GOOD/BAD) and tests/listing_test.py: new URL passes, old passes, category/search pages fail.
- No compare logic change. Offline only.
