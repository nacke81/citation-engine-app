# 2026-11-03: a missing field must be a gap, not a pass

- compare() verified the street and phone, and treated absent city/zip as nothing to compare, so a street-only block returned match. Guards must require presence, not just absence of contradiction.
- Test the exact partial text from the report, and keep the real-page fixtures at match.
- Audit stored proof before tightening: of 17 live rows only 5 store a NAP string; re-read the rest signed out.
