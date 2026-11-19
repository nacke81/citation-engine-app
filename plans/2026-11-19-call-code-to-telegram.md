# Plan: a Directory call code reaches Mike as a Telegram line (t_262cb861)

Cites lesson `docs/lessons/2026-11-18-two-sources-one-page-must-agree.md` (latest by name at start): a new source may fill a gap but must never override or hide a value that contradicts it. Here: a transcript digit string is accepted only when the read-aloud agrees with itself (the same digits twice) or is the single unambiguous run; two different candidate codes -> no code, a "could not read" line instead of a guess.

## Step 1 finding (read-only, Twilio API, 2026-11-19)
Inbound calls to (629) 280-2578 on 11/18, each with a child leg to Mike's cell and no recording:
- d11c8e66: parent CAb453bf 16:55:08Z, 4 s, child to cell 4 s, recordings 0.
- 0cfb830a: parent CA8e9015 17:43:37Z, 4 s, child to cell 4 s, recordings 0.
(A third 4-5 s call at 17:52:35Z is the direct Alignable verify by Mike; a 17:27 call was a separate 10 s pair.)
Both landed Wed 10:55 and 11:43 CT: inside the Function's weekdays 9-5 window, so Function nm-public-line forwarded the call to Mike's cell. Forwarded legs are not recorded, so no voicemail, no recording, no Telegram. The cron (every 5 min) works as built: it only reports recordings. Broken stage: routing, before any recording exists. Code never existed anywhere we can read.

## Change (this PR, app repo only)
New `job/call_code.py` + `tests/call_code_test.py`, wired into CI:
- `extract_code(transcript)`: digits, grouped digits ("123 456", "1-2-3-4"), spoken digits ("one two three four"), repeated read. 4-8 digits. Two different candidates -> None.
- `run_once(client, transcribe, state_path, since)`: for each NEW recording on the line (state file holds recording SIDs only, never a code or transcript), transcribe, extract, return ONE Telegram line per recording: `NM line call code: 123456 (heard HH:MM CT)` or `NM line call: recording heard, no code found` . Never prints a recording URL with the code.
- Default client = Twilio read-only REST (creds file path from env, same file the inbox cron uses); default transcriber = local faster-whisper helper. Both injected in tests; no network, no real code.
- Never writes the code to disk or log; stdout is the Telegram body (no_agent cron convention: empty stdout = nothing).
- Never touches the portal or any Directory; read-only toward Twilio.

## Not in this PR (needs Nate + Mike, a Twilio Function change = deploy)
Function nm-public-line must record (and not forward) a Directory verification call inside 9-5. Proposed rule: calls from a number that is not Mike's allow-listed callers -> Record + no Dial during a Verify Now phone-call window, or simply Record always and ring cell. Source of the Function is not in any repo I can read. Card for hostadmin/Nate.

## Tests (red first)
extract: plain, spaced, dashed, spoken, repeated, two-different -> None, too short, too long, none. run_once: new recording -> one line with code; second pass -> nothing (state); no-code transcript -> "no code found" line; transcriber raising -> one safe line, state NOT advanced; state file and stdout of a second pass contain no digits of the code; recording older than `since` skipped; module imports no portal and has no Directory call.
