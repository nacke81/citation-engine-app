"""Directory call code -> one Telegram line (t_262cb861).

A Directory "phone-call" verification reads a code aloud to the NM line. When the call is recorded (voicemail), this reads the new
recording, transcribes it on this box (local faster-whisper, no API cost), extracts the digits, and prints ONE line per recording that
carried a code, for a no_agent cron to deliver to Telegram (empty stdout = nothing new), the same way an SMS code lands.

  python job/call_code.py --since 2026-11-19T00:00:00Z [--state FILE]

The NM line is read at runtime (env CE_NM_LINE, else the creds file's "NM public NAP" provisioned number); no number lives in the repo.

Rules this module holds:
  * Read-only toward Twilio (GET only). It never imports the portal and never touches a Directory.
  * The code is printed on stdout (that is the product) and goes nowhere else: the state file holds recording SIDs and try counts only,
    no transcript, no code, and failures print a fixed phrase, never exception text.
  * Digits count only right after a code cue (code / passcode / verification / pin / otp; not zip, area, postal, promo, coupon or discount code). No cue -> no line: the inbound-voicemail cron
    already reports ordinary voicemails.
  * Only a recording whose CALL STARTED inside an armed Verify Now window (job/verify_arm.py's local window log) is read at all. Outside every window
    nothing is transcribed and nothing is printed: that is the structural answer to a customer voicemail such as "the gate pin is 4455". No windows
    file = no windows = silence. The window log can only narrow what is reported; it never turns a transcript without a code cue into a code.
  * Two different candidate codes in one recording -> no code, never a guess.
  * A transcription failure is retried, at most MAX_TRIES times per recording, then one final line and the SID is marked seen.
"""
import argparse, base64, datetime, email.utils, json, os, re, subprocess, sys, tempfile, urllib.parse, urllib.request

# (run as a script, job/ is already on sys.path; tests add it)
import verify_arm as AR   # stdlib only: the local arm-window log (t_282b646e). No portal, no Directory.

CRED_PATH = os.environ.get("CE_TWILIO_CREDENTIALS", "C:/Credentials/twilio-api.json")
WHISPER_SCRIPT = os.environ.get("CE_WHISPER_SCRIPT", "C:/Users/Mikes Desktop 2023/Documents/Claude/Claude Code/vault-calls-and-texts/scripts/transcribe_faster_whisper.py")
MIN_DIGITS, MAX_DIGITS = 4, 8
MAX_TRIES = 3
CUE_WINDOW = 40
WORDS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}
CUE_RE = re.compile(r"\b(?<!zip )(?<!area )(?<!postal )(?<!promo )(?<!coupon )(?<!discount )(?:code|passcode|verification|pin|otp)s?\b")
E164_RE = re.compile(r"\+[1-9]\d{7,14}")


class LineConfigError(Exception):
    pass


def resolve_line(env=None, cred_path=None):
    """The NM line (E.164): env CE_NM_LINE, else the creds file's NM public NAP number. Raises LineConfigError."""
    v = ((env if env is not None else os.environ).get("CE_NM_LINE") or "").strip()
    if not v:
        try:
            with open(cred_path or CRED_PATH, encoding="utf8") as f:
                for p in json.load(f).get("provisioned_numbers", []):
                    if "nm public nap" in (str(p.get("purpose", "")) + " " + str(p.get("friendly_name", ""))).lower():
                        v = str(p.get("number", "")).strip()
                        break
        except (OSError, ValueError, AttributeError):
            pass
    if not E164_RE.fullmatch(v):
        raise LineConfigError("NM line missing or not E.164")
    return v


def _runs(t):
    """[(start, digits)] for each digit run. Space/dash join groups; ', ' '. ' '- ' join only single digits (Whisper reads 4, 8, 2)."""
    out, cur = [], None   # cur = [start, end, digits, last_token_len]
    for m in re.finditer(r"\d+", t):
        if cur:
            gap = t[cur[1]:m.start()]
            if re.fullmatch(r"[\s\-]+", gap) or (cur[3] == 1 and len(m.group()) == 1 and re.fullmatch(r"[,.\-]\s*", gap)):
                cur[1], cur[2], cur[3] = m.end(), cur[2] + m.group(), len(m.group())
                continue
            out.append((cur[0], cur[2]))
        cur = [m.start(), m.end(), m.group(), len(m.group())]
    if cur:
        out.append((cur[0], cur[2]))
    return out


def _unrepeat(d):
    """A code read back to back ("4 8 2 9 1 3. 4 8 2 9 1 3.") joins into one run: k exact copies of a 4-8 digit unit -> the unit."""
    for n in range(MIN_DIGITS, MAX_DIGITS + 1):
        if len(d) > n and len(d) % n == 0 and d == d[:n] * (len(d) // n):
            return d[:n]
    return d


def extract_code(transcript):
    """-> the code (str of 4-8 digits) or None. Only digits right after a code cue count; two different candidates -> None."""
    if not transcript or not isinstance(transcript, str):
        return None
    t = transcript.lower()
    t = re.sub(r"\b(" + "|".join(WORDS) + r")\b", lambda m: WORDS[m.group(1)], t)
    for _ in range(4):   # "oh" is a digit only next to a digit
        t = re.sub(r"(?<=\d )oh\b|(?<=\d, )oh\b|(?<=\d\. )oh\b|\boh(?=[ ,.\-]+\d)", "0", t)
    runs = _runs(t)
    cands = set()
    for cue in CUE_RE.finditer(t):
        after = [d for s, d in runs if cue.end() <= s <= cue.end() + CUE_WINDOW]
        if after:
            d = _unrepeat(after[0])
            if MIN_DIGITS <= len(d) <= MAX_DIGITS:   # the first run after the cue is the code; a phone number later is not
                cands.add(d)
    return cands.pop() if len(cands) == 1 else None


def _heard(created):
    try:
        dt = datetime.datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return "?"
    try:
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo("America/Chicago")).strftime("%H:%M CT")
    except Exception:   # no tz database on this box: say UTC rather than a wrong CT
        return dt.strftime("%H:%M UTC")


def _load_state(path):
    try:
        with open(path, encoding="utf8") as f:
            d = json.load(f)
        return set(d.get("seen", [])), {k: int(v) for k, v in d.get("fails", {}).items()}
    except (OSError, ValueError, AttributeError):
        return set(), {}


def _save_state(path, seen, fails):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf8") as f:
        json.dump({"seen": sorted(seen), "fails": fails}, f)


def _log_failure(state_path, sid, exc):
    """Why a transcription failed, for the operator (t_f5233f56): UTC time, sid, exception type, return code, last stderr line of the helper with
    every digit masked. Never the transcript, never in a Telegram line or the state. A log failure never changes the result."""
    try:
        err = getattr(exc, "stderr", None) or b""
        if isinstance(err, bytes):
            err = err.decode("utf8", "replace")
        tail = re.sub(r"\d", "#", (err.strip().splitlines() or [""])[-1])[:200]
        rc = getattr(exc, "returncode", "-")
        with open(os.path.join(os.path.dirname(os.path.abspath(state_path)), "call-code-errors.log"), "a", encoding="utf8") as f:
            f.write("%s %s %s rc=%s stderr_tail=%s\n" % (datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), sid, type(exc).__name__, rc, tail))
    except Exception:
        pass


def run_once(client, transcribe, state_path, since_iso, windows=None):
    """-> list of Telegram lines (possibly empty). A recording is marked seen once transcribed, or after MAX_TRIES failed attempts.
    `windows` = the armed windows (verify_arm.load_windows). None or [] means no window: every recording is skipped (seen, never transcribed, no line)."""
    windows = windows or []
    seen, fails = _load_state(state_path)
    lines, dirty = [], False
    for rec in sorted(client.recordings_since(since_iso), key=lambda r: r["created"]):
        sid = rec["sid"]
        if sid in seen:
            continue
        dirty = True
        if not AR.in_window(rec.get("started") or rec["created"], windows):   # a customer voicemail, not the Directory's robot: the inbound cron reports it
            seen.add(sid)
            continue
        try:
            text = transcribe(client.audio(sid))
        except Exception as exc:   # never echo the exception text: it could carry the transcript
            _log_failure(state_path, sid, exc)
            n = fails.get(sid, 0) + 1
            if n >= MAX_TRIES:
                lines.append("NM line call: heard %s, could not transcribe the recording after %d tries (giving up)" % (_heard(rec["created"]), MAX_TRIES))
                seen.add(sid)
                fails.pop(sid, None)
            else:
                fails[sid] = n
                lines.append("NM line call: heard %s, could not transcribe the recording (will retry)" % _heard(rec["created"]))
            continue
        code = extract_code(text)
        if code:
            lines.append("NM line call code: %s (heard %s)" % (code, _heard(rec["created"])))
        seen.add(sid)
        fails.pop(sid, None)
    if dirty:
        _save_state(state_path, seen, fails)
    return lines


class TwilioClient:
    """Read-only (GET). Credentials file keys account_sid/auth_token (or camelCase), the same file the NM inbox cron reads."""

    def __init__(self, cred_path=None, line=None):
        with open(cred_path or CRED_PATH, encoding="utf8") as f:
            c = json.load(f)
        self.sid = c.get("accountSid") or c.get("account_sid") or c.get("TWILIO_ACCOUNT_SID")
        tok = c.get("authToken") or c.get("auth_token") or c.get("TWILIO_AUTH_TOKEN")
        if not self.sid or not tok:
            raise RuntimeError("credential file incomplete")
        self.auth = "Basic " + base64.b64encode(("%s:%s" % (self.sid, tok)).encode()).decode()
        self.line = line or resolve_line(cred_path=cred_path)

    def _get(self, path, raw=False):
        req = urllib.request.Request("https://api.twilio.com" + path, headers={"Authorization": self.auth}, method="GET")
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
        return body if raw else json.loads(body)

    def recordings_since(self, since_iso):
        base = "/2010-04-01/Accounts/%s" % self.sid
        q = urllib.parse.urlencode({"To": self.line, "StartTime>": since_iso[:10], "PageSize": "100"})
        out = []
        for call in self._get("%s/Calls.json?%s" % (base, q)).get("calls", []):
            q2 = urllib.parse.urlencode({"CallSid": call["sid"]})
            for r in self._get("%s/Recordings.json?%s" % (base, q2)).get("recordings", []):
                created = _iso(r.get("date_created"))
                if created >= since_iso:
                    started = _iso(call["start_time"]) if call.get("start_time") else created   # the CALL's start decides the window, not the recording's
                    out.append({"sid": r["sid"], "created": created, "started": started})
        return out

    def audio(self, sid):
        return self._get("/2010-04-01/Accounts/%s/Recordings/%s.mp3" % (self.sid, sid), raw=True)


def _iso(rfc2822):
    dt = email.utils.parsedate_to_datetime(rfc2822)
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def whisper_transcribe(audio):
    """Local faster-whisper via the box's helper script. Temp files live only for the call. An empty transcript raises (counts as a failure)."""
    with tempfile.TemporaryDirectory() as d:
        a, o = os.path.join(d, "in.mp3"), os.path.join(d, "out.txt")
        with open(a, "wb") as f:
            f.write(audio)
        subprocess.run([sys.executable, WHISPER_SCRIPT, "--audio", a, "--output", o], check=True, capture_output=True, timeout=300)
        with open(o, encoding="utf8") as f:
            text = f.read()
    if not text.strip():
        raise RuntimeError("empty transcript")
    return text


def main(argv=None, client=None, transcribe=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True, help="ISO UTC, e.g. 2026-11-19T00:00:00Z; only newer recordings are read")
    ap.add_argument("--state", default=os.path.join(os.environ.get("LOCALAPPDATA", "."), "citation-engine", "logs", "call-code-seen.json"))
    ap.add_argument("--windows", default=None, help="the armed-window log (default: verify_arm's CE_VERIFY_WINDOWS / LOCALAPPDATA path)")
    a = ap.parse_args(argv)
    try:
        if client is None:
            try:
                client = TwilioClient(line=resolve_line())
            except LineConfigError:
                print("NM line call: call-code reader has no valid NM line (set CE_NM_LINE); no code read")
                return 1
        lines = run_once(client, transcribe or whisper_transcribe, a.state, a.since, AR.load_windows(a.windows))
    except Exception:
        print("NM line call: call-code reader failed (see the box; no code read)")
        return 1
    for l in lines:
        print(l)
    return 0


if __name__ == "__main__":
    sys.exit(main())
