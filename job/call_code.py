"""Directory call code -> one Telegram line (t_262cb861).

A Directory "phone-call" verification reads a code aloud to the NM line (629) 280-2578. When the call is recorded (voicemail), this reads the
new recording, transcribes it on this box (local faster-whisper, no API cost), extracts the digits, and prints ONE line per recording for a
no_agent cron to deliver to Telegram (empty stdout = nothing new), the same way an SMS code lands.

  python job/call_code.py --since 2026-11-19T00:00:00Z [--state FILE]

Rules this module holds:
  * Read-only toward Twilio (GET only). It never imports the portal and never touches a Directory.
  * The code is printed on stdout (that is the product) and goes nowhere else: the state file holds recording SIDs only, no transcript,
    no code, and failures print a fixed phrase, never exception text.
  * Two different candidate codes in one recording -> no code (a "no code found" line), never a guess.
  * A transcription failure does not mark the recording seen, so the next pass retries it.
"""
import argparse, base64, json, os, re, subprocess, sys, tempfile, urllib.parse, urllib.request

LINE = "+16292802578"
CRED_PATH = os.environ.get("CE_TWILIO_CREDENTIALS", "C:/Credentials/twilio-api.json")
WHISPER_SCRIPT = os.environ.get("CE_WHISPER_SCRIPT", "C:/Users/Mikes Desktop 2023/Documents/Claude/Claude Code/vault-calls-and-texts/scripts/transcribe_faster_whisper.py")
MIN_DIGITS, MAX_DIGITS = 4, 8
WORDS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}
RUN_RE = re.compile(r"\d(?:[\s,\-]?\d)*")


def extract_code(transcript):
    """-> the code (str of 4-8 digits) or None. Spoken digits, grouped digits and a repeated read all work; two different candidates -> None."""
    if not transcript or not isinstance(transcript, str):
        return None
    t = transcript.lower()
    t = re.sub(r"\b(" + "|".join(WORDS) + r")\b", lambda m: WORDS[m.group(1)], t)
    for _ in range(3):   # "oh" is a digit only next to a digit
        t = re.sub(r"(?<=\d )oh\b|\boh(?= \d)", "0", t)
    cands = set()
    for m in RUN_RE.finditer(t):
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) > MAX_DIGITS:
            continue   # a reference/phone number, not a code
        if len(digits) >= MIN_DIGITS:
            cands.add(digits)
    return cands.pop() if len(cands) == 1 else None


def _heard(created):
    m = re.search(r"T(\d\d:\d\d)", created or "")
    return (m.group(1) + "Z") if m else "?"


def _load_seen(path):
    try:
        with open(path, encoding="utf8") as f:
            return set(json.load(f).get("seen", []))
    except (OSError, ValueError):
        return set()


def _save_seen(path, seen):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf8") as f:
        json.dump({"seen": sorted(seen)}, f)


def run_once(client, transcribe, state_path, since_iso):
    """-> list of Telegram lines (possibly empty). Marks a recording seen only after it was transcribed."""
    seen = _load_seen(state_path)
    lines = []
    for rec in sorted(client.recordings_since(since_iso), key=lambda r: r["created"]):
        if rec["sid"] in seen:
            continue
        try:
            text = transcribe(client.audio(rec["sid"]))
        except Exception:   # never echo the exception text: it could carry the transcript
            lines.append("NM line call: heard %s, could not transcribe the recording (will retry)" % _heard(rec["created"]))
            continue
        code = extract_code(text)
        if code:
            lines.append("NM line call code: %s (heard %s)" % (code, _heard(rec["created"])))
        else:
            lines.append("NM line call: recording heard %s, no code found" % _heard(rec["created"]))
        seen.add(rec["sid"])
    if lines:
        _save_seen(state_path, seen)
    return lines


class TwilioClient:
    """Read-only (GET). Credentials file keys accountSid/authToken, the same file the NM inbox cron reads."""

    def __init__(self, cred_path=CRED_PATH, line=LINE):
        with open(cred_path, encoding="utf8") as f:
            c = json.load(f)
        self.sid = c.get("accountSid") or c.get("account_sid") or c.get("TWILIO_ACCOUNT_SID")
        tok = c.get("authToken") or c.get("auth_token") or c.get("TWILIO_AUTH_TOKEN")
        if not self.sid or not tok:
            raise RuntimeError("credential file incomplete")
        self.auth = "Basic " + base64.b64encode(("%s:%s" % (self.sid, tok)).encode()).decode()
        self.line = line

    def _get(self, path, raw=False):
        req = urllib.request.Request("https://api.twilio.com" + path, headers={"Authorization": self.auth}, method="GET")
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
        return body if raw else json.loads(body)

    def recordings_since(self, since_iso):
        base = "/2010-04-01/Accounts/%s" % self.sid
        day = since_iso[:10]
        q = urllib.parse.urlencode({"To": self.line, "StartTime>": day, "PageSize": "100"})
        out = []
        for call in self._get("%s/Calls.json?%s" % (base, q)).get("calls", []):
            q2 = urllib.parse.urlencode({"CallSid": call["sid"]})
            for r in self._get("%s/Recordings.json?%s" % (base, q2)).get("recordings", []):
                created = _iso(r.get("date_created"))
                if created >= since_iso:
                    out.append({"sid": r["sid"], "created": created})
        return out

    def audio(self, sid):
        return self._get("/2010-04-01/Accounts/%s/Recordings/%s.mp3" % (self.sid, sid), raw=True)


def _iso(rfc2822):
    import email.utils
    dt = email.utils.parsedate_to_datetime(rfc2822)
    return dt.astimezone(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def whisper_transcribe(audio):
    """Local faster-whisper via the box's helper script. Temp files live only for the call."""
    with tempfile.TemporaryDirectory() as d:
        a, o = os.path.join(d, "in.mp3"), os.path.join(d, "out.txt")
        with open(a, "wb") as f:
            f.write(audio)
        subprocess.run([sys.executable, WHISPER_SCRIPT, "--audio", a, "--output", o], check=True, capture_output=True, timeout=300)
        with open(o, encoding="utf8") as f:
            return f.read()


def main(argv=None, client=None, transcribe=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True, help="ISO UTC, e.g. 2026-11-19T00:00:00Z; only newer recordings are read")
    ap.add_argument("--state", default=os.path.join(os.environ.get("LOCALAPPDATA", "."), "citation-engine", "logs", "call-code-seen.json"))
    a = ap.parse_args(argv)
    try:
        client = client or TwilioClient()
        lines = run_once(client, transcribe or whisper_transcribe, a.state, a.since)
    except Exception:
        print("NM line call: call-code reader failed (see the box; no code read)")
        return 1
    for l in lines:
        print(l)
    return 0


if __name__ == "__main__":
    sys.exit(main())
