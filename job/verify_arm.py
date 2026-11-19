"""Arm / disarm the NM public line for a Directory phone-call verification (t_282b646e).

While a Verify Now phone-call request is out, the Twilio Function `nm-public-line` must RECORD the Directory's robot call instead of
forwarding it to a cell. The Function reads one Twilio Sync document:

    service  IS36a9f8f48c4dba0472d019ea83eac69e   document  verify_armed   data  {"verify_armed_until": "<ISO-8601 UTC>"}

and treats the line as armed only if now < until AND now < the document's date_updated + 15 min. Any error or a 2 s timeout there means
"not armed" (forward as usual), so a failed arm or a failed disarm here is never fatal: the TTL and the 15-minute rule cap it.

  arm(request_id)    POST /Documents (UniqueName, Data, Ttl); on 409 POST /Documents/verify_armed.   until = now + 12 min.
  disarm(request_id) DELETE /Documents/verify_armed (404 = already gone = ok).

Both return a bool and never raise. Credentials come from the same file call_code.py reads; they are never printed or logged.
A small local window log (ids and times only, no number, no code) records when the line was armed, so call_code.py can tell a Directory
robot call from an ordinary customer voicemail: only a recording whose call started inside a window may become a code line.
"""
import base64, datetime, json, os, sys, urllib.error, urllib.parse, urllib.request

SYNC_SERVICE = "IS36a9f8f48c4dba0472d019ea83eac69e"
DOC = "verify_armed"
ARM_MINUTES = 12
TTL_S = 900   # the Function's own hard cap (15 min) - the document disappears by itself even if a disarm is lost
TIMEOUT_S = 5
KEEP = 50
CRED_PATH = os.environ.get("CE_TWILIO_CREDENTIALS", "C:/Credentials/twilio-api.json")


def log(msg):
    print("[verify_arm] " + msg, file=sys.stderr, flush=True)


def windows_path():
    return os.environ.get("CE_VERIFY_WINDOWS") or os.path.join(os.environ.get("LOCALAPPDATA", "."), "citation-engine", "logs", "verify-armed-windows.json")


def iso(dt):
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(ts):
    try:
        return datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return None


# ---- window log ---------------------------------------------------------------------------------------------------------------------
def load_windows(path=None):
    """-> list of {request_id, start, until, end}. A missing or unreadable file is an empty list (nothing is armed that we know of)."""
    try:
        with open(path or windows_path(), encoding="utf8") as f:
            d = json.load(f)
        return [w for w in d.get("windows", []) if isinstance(w, dict) and parse(w.get("start")) and parse(w.get("until"))]
    except (OSError, ValueError, AttributeError):
        return []


def save_windows(ws, path=None):
    p = path or windows_path()
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    with open(p, "w", encoding="utf8") as f:
        json.dump({"windows": ws[-KEEP:]}, f)


def in_window(when_iso, windows):
    """True when the instant `when_iso` falls inside a window [start, end or until]. Unparseable time -> False."""
    t = parse(when_iso)
    if not t:
        return False
    for w in windows:
        lo, hi = parse(w["start"]), parse(w.get("end") or w["until"])
        if lo and hi and lo <= t <= hi:
            return True
    return False


# ---- Twilio Sync --------------------------------------------------------------------------------------------------------------------
class SyncArm:
    """Real arm/disarm. `transport(method, url, form)` -> (status, body) is injectable; the default is urllib with Basic auth."""

    def __init__(self, cred_path=None, transport=None, now=None, windows=None):
        self._cred_path, self._transport, self._now, self._windows = cred_path or CRED_PATH, transport, now, windows
        self._auth = None

    def _clock(self):
        return self._now() if self._now else datetime.datetime.now(datetime.timezone.utc)

    def _basic(self):
        if self._auth is None:
            with open(self._cred_path, encoding="utf8") as f:
                c = json.load(f)
            sid = c.get("account_sid") or c.get("accountSid") or c.get("TWILIO_ACCOUNT_SID")
            tok = c.get("auth_token") or c.get("authToken") or c.get("TWILIO_AUTH_TOKEN")
            if not sid or not tok:
                raise RuntimeError("credential file incomplete")
            self._auth = "Basic " + base64.b64encode(("%s:%s" % (sid, tok)).encode()).decode()
        return self._auth

    def _call(self, method, url, form=None):
        if self._transport:
            return self._transport(method, url, form)
        if os.environ.get("CE_NO_TWILIO"):   # tests set this: a real network call is refused before any credential is read
            raise RuntimeError("Twilio is fenced off in this process")
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={"Authorization": self._basic()})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, b""

    def _url(self, tail=""):
        return "https://sync.twilio.com/v1/Services/%s/Documents%s" % (SYNC_SERVICE, tail)

    def arm(self, request_id):
        """-> True when the document is set. Never raises. Records the window locally only after Twilio accepted it."""
        now = self._clock()
        until = now + datetime.timedelta(minutes=ARM_MINUTES)
        data = json.dumps({"verify_armed_until": iso(until)})
        try:
            st, _ = self._call("POST", self._url(), {"UniqueName": DOC, "Data": data, "Ttl": str(TTL_S)})
            if st == 409:
                st, _ = self._call("POST", self._url("/" + DOC), {"Data": data, "Ttl": str(TTL_S)})
            if st not in (200, 201):
                log("arm refused: HTTP %s; the line keeps forwarding" % st)
                return False
        except Exception as e:
            log("arm failed: %s; the line keeps forwarding" % type(e).__name__)
            return False
        try:
            ws = load_windows(self._windows)
            ws.append({"request_id": request_id, "start": iso(now), "until": iso(until), "end": None})
            save_windows(ws, self._windows)
        except Exception as e:
            log("window log not written: %s" % type(e).__name__)
        log("armed for %s until %s" % (request_id, iso(until)))
        return True

    def disarm(self, request_id=None):
        """-> True when the document is gone. Never raises. With a request id, only this request's own window is closed; another
        request's open window leaves the document alone."""
        try:
            ws = load_windows(self._windows)
        except Exception:
            ws = []
        if request_id:   # only a NEWER, still-open window of another request holds the line; an older stale one (a crashed run) never blocks this disarm
            own = [w["start"] for w in ws if w.get("request_id") == request_id]
            newer = [w for w in ws if not w.get("end") and w.get("request_id") != request_id and parse(w["until"]) > self._clock() and own and w["start"] > min(own)]
            if newer:
                log("disarm skipped for %s: another request holds the line" % request_id)
                return True
        try:
            st, _ = self._call("DELETE", self._url("/" + DOC))
            if st not in (200, 202, 204, 404):
                log("disarm refused: HTTP %s; the TTL and the 15-minute rule will close it" % st)
                return False
        except Exception as e:
            log("disarm failed: %s; the TTL and the 15-minute rule will close it" % type(e).__name__)
            return False
        try:
            now = iso(self._clock())
            for w in ws:
                if not w.get("end") and (not request_id or w.get("request_id") == request_id):
                    w["end"] = now
            save_windows(ws, self._windows)
        except Exception as e:
            log("window log not closed: %s" % type(e).__name__)
        log("disarmed" + (" for %s" % request_id if request_id else ""))
        return True

    def armed_request(self):
        """The request id of the newest window still open now (local log), else None."""
        now = self._clock()
        for w in reversed(load_windows(self._windows)):
            if not w.get("end") and parse(w["until"]) > now:
                return w.get("request_id")
        return None


if __name__ == "__main__":   # manual: python job/verify_arm.py arm|disarm <request-id>   (live Twilio write - proof runs only)
    a = SyncArm()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    rid = sys.argv[2] if len(sys.argv) > 2 else "manual"
    if cmd not in ("arm", "disarm"):
        print("usage: verify_arm.py arm|disarm <request-id>"); sys.exit(2)
    ok = a.arm(rid) if cmd == "arm" else a.disarm(rid)
    print(("armed" if cmd == "arm" else "disarmed") if ok else "failed")
    sys.exit(0 if ok else 1)
