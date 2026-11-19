# 2026-11-19 call_code: keep the reason a transcription failed (t_f5233f56)

Latest lesson read: docs/lessons/2026-11-19-gate-on-the-window-not-the-words.md (keep what the reader needs where it can still see it; the log may only narrow what is reported). Latest plan read: plans/2026-11-19-verify-arm-call-window.md.

Live finding (post-merge proof, run at 20:49Z): the armed window worked and the NM call-code cron delivered to Telegram (ok, no delivery error), but the line read "could not transcribe the recording" three times, while the identical recording transcribes in 9 s when call_code is run by hand, bare env, scheduler env (build_subprocess_env, hidden flags), and the cron profile HOME. The cron pass swallows the exception text on purpose (it could carry a transcript) and so the cause is invisible.

Change: `run_once` appends one line per failed try to `call-code-errors.log` next to the state file: UTC time, recording sid, exception type, return code, and the last stderr line of the whisper helper with every digit masked to `#`. Never the transcript, never the audio, never in the Telegram line or state. A log write failure never changes the result. The Telegram lines are unchanged.

Tests (red first), tests/call_code_test.py: failure writes the log with type + returncode + masked stderr tail; planted digits in the exception text and stderr never reach the log or lines; log failure (unwritable dir) leaves lines identical; success writes no log; Telegram lines identical to before.

No Directory traffic, no portal, no spend.
