# Plan 2026-10-27: postcard_step_test must never create real Kanban cards

Card t_20ccb0b4. Cites the latest lesson, docs/lessons/2026-10-26-unreadable-was-the-wrong-url.md: before blaming a component, print what it was actually given. Here: cases 4 and 7 call `run()` without `alert=`, so `_default_alert` reached `subprocess.run` and the real hermes CLI. CI hid it (no hermes -> silent CARD FAILED).

## Changes
1. job/postcard_step.py: `_default_alert` returns early with `POSTCARD ALERT CARD SKIPPED: CE_NO_CARDS` (stderr) when env `CE_NO_CARDS=1`. No file writes added.
2. tests/postcard_step_test.py:
   - set `CE_NO_CARDS=1` at top; tripwire `PS._card_runner` and `PS.subprocess.run` record argv into `leaked`, run nothing.
   - cases 4 and 7 pass `alert=` list append (assertions unchanged).
   - section 14 clears CE_NO_CARDS and uses its own fake_runner; afterwards tripwire and env restored.
   - new test of the CE_NO_CARDS branch; final check `leaked == []`.
3. Lesson doc after the build.

## Proof
Run the test locally with CE_NO_CARDS unset in the shell; list board citations cards titled POSTCARD ALERT% created after the run: expect 0. Run full suite and leak_check.
