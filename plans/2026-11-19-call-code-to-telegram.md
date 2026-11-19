# Plan: a Directory call code reaches Mike as a Telegram line (t_262cb861)

Cites lesson `docs/lessons/2026-11-18-two-sources-one-page-must-agree.md` (latest by name at start): a new source may fill a gap but must never override or hide a value that contradicts it. Here: a transcript digit string is accepted only after a code cue and only when it is the single unambiguous run; two different candidate codes -> no code, never a guess.

## Step 1 finding (read-only, Twilio API, 2026-11-19)
Inbound calls to the NM line on 11/18, each with a child leg to Mike's cell and no recording:
- d11c8e66: parent CAb453bf 16:55:08Z (10:55 CT), 4 s, child to cell 4 s, recordings 0.
- 0cfb830a: parent CA8e9015 17:43:37Z (11:43 CT), 4 s, child to cell 4 s, recordings 0.
Both landed on a weekday inside the Function's 9-5 window, so Function nm-public-line forwarded the call to Mike's cell, and `/after-dial` hung up on `DialCallStatus=completed`, so `/voicemail` never ran. Forwarded legs are not recorded: no voicemail, no recording, no Telegram. The 5-min inbound cron works as built; it only reports recordings. Broken stage: routing, before any recording exists.

## Change (this PR, app repo only)
New `job/call_code.py` + `tests/call_code_test.py`, wired into CI:
- The NM line is read at runtime: env `CE_NM_LINE`, else the creds file `provisioned_numbers` entry whose purpose says "NM public NAP". Missing or not E.164 -> rc 1 with a fixed phrase. No number in the repo.
- `extract_code(transcript)`: digits only after a code cue (`code`, `verification`, `pin`, `passcode`, `otp`) within a short window; digit runs may be grouped ("482 913"), dashed, spoken ("four, eight"), or Whisper-style ("4, 8, 2, 9" / "4. 8. 2."). 4-8 digits. Two different candidates -> None. No cue -> None.
- `run_once`: one Telegram line per NEW recording with a code: `NM line call code: N (heard HH:MM CT)`. No cue/code -> NO line (the existing inbound cron already reports the voicemail). Transcription failure: 2 "will retry" lines, then one final "gave up" line on try 3 and the SID is marked seen; the state holds SIDs and counts only, never a code or transcript.
- Read-only toward Twilio (GET only), never touches the portal or a Directory.

## Not in this PR
- Routing fix (record, don't forward, while a phone-call verify is armed): card t_82d78cf2 (Function source into the repo plus a Sync `verify-window` flag); the Function deploy is its own step there. No card is cut from here.
- Registering the no_agent cron for `call_code.py --since` and the bridge arm/clear signal: follow-ups after merge, owned by Nate.

## Tests (red first)
extract: plain, spaced, dashed, spoken, repeated, two-different, too short, too long, none; the three Whisper-style shapes; no-cue probes ("555-1234", "1234 Main Street", "from 37203") -> None. run_once: new recording -> one line; second pass silent; no code -> no line; failure x3 then a silent 4th pass; state has no code; old recording skipped. TwilioClient through a fake `_get`: exact `Calls.json` query (To = configured line, `StartTime>`, GET only); a mutation restoring the masked constant fails it. Line config refusal. CT label via zoneinfo (`uv run --with tzdata` on Windows).
