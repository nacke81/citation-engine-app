"""call_code tests (t_262cb861). Fake Twilio client, fake transcriber, fake digits only. No network, no whisper, no portal, no real code.
Run: python tests/call_code_test.py   exit 1 on any failure   (Windows needs a tz database: uv run --with tzdata python tests/call_code_test.py)
"""
import contextlib, io, json, os, sys, tempfile, urllib.parse
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import call_code as C

FAILS = []
FAKE_LINE = "+15550001234"   # fake E.164 for the config tests, not a real line


def check(name, cond, detail=""):
    if not cond:
        FAILS.append(name)
        print("FAIL", name, detail)


class FakeClient:
    def __init__(self, recs): self.recs = recs; self.fetched = []
    def recordings_since(self, since_iso): return [r for r in self.recs if r["created"] >= since_iso]
    def audio(self, sid): self.fetched.append(sid); return b"fake-audio-" + sid.encode()


def transcriber(texts):
    def t(audio):
        sid = audio.decode().split("fake-audio-")[1]
        v = texts[sid]
        if isinstance(v, Exception): raise v
        return v
    return t


# ---- extract_code ----
FAKE = "482913"   # fake, never a live code
for label, text, want in [
    ("plain", "Your verification code is 482913.", FAKE),
    ("spaced groups", "Your code is 482 913. Again, 482 913.", FAKE),
    ("dashed", "code 4-8-2-9-1-3", FAKE),
    ("spoken", "your code is four eight two nine one three", FAKE),
    ("spoken oh/zero", "your code is four zero oh nine", "4009"),
    ("repeated", "Your code is 482913. I repeat, 482913.", FAKE),
    ("two different", "code 482913 ... code 135790", None),
    ("too short", "your code is 12", None),
    ("too long", "your code is 123456789012", None),
    ("none", "Hello, please leave a message.", None),
    ("empty", "", None),
    ("None", None, None),
    # Whisper-style
    ("whisper commas", "Your verification code is 4, 8, 2, 9, 1, 3.", FAKE),
    ("whisper periods", "Your code is 4. 8. 2. 9. 1. 3.", FAKE),
    ("whisper words", "code is: four, eight, two, nine.", "4829"),
    ("whisper oh", "your code is four, oh, nine, two.", "4092"),
    ("passcode", "Your passcode is 482913.", FAKE),
    ("pin", "Your PIN is 4829.", "4829"),
    # customer voicemails: no cue -> no code
    ("vm phone number", "Hi, call me back at 555-1234 please.", None),
    ("vm street", "Hi, I'm at 1234 Main Street, call me.", None),
    ("vm zip", "This is a call from 37203, thanks.", None),
    # a cue, then a later phone number: the first run after the cue wins; a phone number alone is not a code
    ("code then phone", "your code is 482913, and my number is 555 123 4567", FAKE),
    ("cue far from digits", "code" + " blah" * 20 + " 482913", None),
    ("sentence period not joined", "your code is 482913. 7 people called", FAKE),
    # round 3: back-to-back repeats
    ("repeat digits", "Your verification code is 4 8 2 9 1 3. 4 8 2 9 1 3.", FAKE),
    ("repeat commas", "Your code is 4, 8, 2, 9, 1, 3. 4, 8, 2, 9, 1, 3.", FAKE),
    ("repeat dashes", "Your code is 4-8-2-9-1-3. 4-8-2-9-1-3.", FAKE),
    ("repeat words", "Your code is four, eight, two, nine, one, three. Four, eight, two, nine, one, three.", FAKE),
    ("triple repeat", "Your code is 4829. 4829. 4829.", "4829"),
    ("repeat then different", "Your code is 4 8 2 9 1 3. 7 7 1 1 2 2.", None),
    ("8 digit non-repeating kept", "Your code is 48291375.", "48291375"),
    # round 3: compound cues are not cues
    ("vm zip code", "my zip code is 37203", None),
    ("vm promo code", "promo code 2026", None),
    ("vm barcode", "the barcode reads 77889900", None),
    ("passcode still works", "Your passcode is 4829.", "4829"),
]:
    got = C.extract_code(text)
    check("extract " + label, got == want, "got %r" % (got,))

# ---- run_once ----
RECS = [
    {"sid": "RE0001", "created": "2026-11-19T15:00:10Z"},
    {"sid": "RE0002", "created": "2026-11-19T15:30:10Z"},
    {"sid": "RE0000", "created": "2026-11-18T01:00:00Z"},   # before since
]
TEXTS = {"RE0001": "Your code is four eight two nine one three. Again: 482913.", "RE0002": "Hi, I'm at 1234 Main Street. Call me back."}
SINCE = "2026-11-19T00:00:00Z"
with tempfile.TemporaryDirectory() as d:
    state = os.path.join(d, "state.json")
    cl = FakeClient(RECS)
    lines = C.run_once(cl, transcriber(TEXTS), state, SINCE)
    check("code recording -> one line, voicemail -> none", len(lines) == 1, lines)
    check("code line has code and CT label", len(lines) == 1 and "482913" in lines[0] and "call code" in lines[0] and "09:00 CT" in lines[0], lines)
    check("old recording not fetched", "RE0000" not in cl.fetched, cl.fetched)
    check("no recording URL in a line", not any("http" in l for l in lines), lines)
    raw = open(state, encoding="utf8").read()
    check("state has no code", "482913" not in raw and "four eight" not in raw and "1234" not in raw, raw)
    check("state has sids", "RE0001" in raw and "RE0002" in raw, raw)
    check("second pass silent", C.run_once(cl, transcriber(TEXTS), state, SINCE) == [])

    # transcription failure: capped at 3 tries per SID, then marked seen, then silent
    state2 = os.path.join(d, "state2.json")
    boom = {"RE0001": RuntimeError("whisper died with 482913 in the message")}
    passes = [C.run_once(FakeClient(RECS[:1]), transcriber(boom), state2, SINCE) for _ in range(4)]
    check("try 1 retry line", len(passes[0]) == 1 and "will retry" in passes[0][0], passes)
    check("try 2 retry line", len(passes[1]) == 1 and "will retry" in passes[1][0], passes)
    check("try 3 final line", len(passes[2]) == 1 and "giving up" in passes[2][0], passes)
    check("4th pass silent", passes[3] == [], passes)
    check("failure never echoes exception text", all("482913" not in l and "whisper" not in l for p in passes for l in p), passes)
    raw2 = open(state2, encoding="utf8").read()
    check("state2 sids/counts only", "482913" not in raw2 and "RE0001" in raw2, raw2)
    # a failure then success resets the count
    state2b = os.path.join(d, "state2b.json")
    C.run_once(FakeClient(RECS[:1]), transcriber(boom), state2b, SINCE)
    l2 = C.run_once(FakeClient(RECS[:1]), transcriber(TEXTS), state2b, SINCE)
    check("retry succeeds", len(l2) == 1 and "482913" in l2[0], l2)

    # main(): stdout carries lines only
    buf = io.StringIO()
    state3 = os.path.join(d, "state3.json")
    with contextlib.redirect_stdout(buf):
        rc = C.main(["--since", SINCE, "--state", state3], client=FakeClient(RECS[:1]), transcribe=transcriber(TEXTS))
    check("main rc 0", rc == 0, rc)
    check("main prints code line", "482913" in buf.getvalue(), buf.getvalue())
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        rc2 = C.main(["--since", SINCE, "--state", state3], client=FakeClient(RECS[:1]), transcribe=transcriber(TEXTS))
    check("main empty when nothing new", rc2 == 0 and buf2.getvalue() == "", buf2.getvalue())
    class Dead:
        def recordings_since(self, s): raise RuntimeError("secret 482913")
    buf3 = io.StringIO()
    with contextlib.redirect_stdout(buf3):
        rc3 = C.main(["--since", SINCE, "--state", state3], client=Dead(), transcribe=transcriber(TEXTS))
    check("main failure rc 1 fixed phrase", rc3 == 1 and "482913" not in buf3.getvalue() and "failed" in buf3.getvalue(), buf3.getvalue())

    # ---- NM line config ----
    cred = os.path.join(d, "cred.json")
    json.dump({"account_sid": "ACfake", "auth_token": "fake", "provisioned_numbers": [
        {"friendly_name": "Other line", "number": "+15550009999"}, {"friendly_name": "x", "purpose": "NM public NAP. Parked.", "number": FAKE_LINE}]}, open(cred, "w"))
    check("line from env", C.resolve_line(env={"CE_NM_LINE": FAKE_LINE}, cred_path=cred) == FAKE_LINE)
    check("line from creds file", C.resolve_line(env={}, cred_path=cred) == FAKE_LINE)
    for label, env, cp in [("missing", {}, os.path.join(d, "nope.json")), ("masked", {"CE_NM_LINE": "+162****2578"}, cred), ("not E.164", {"CE_NM_LINE": "5550002345"}, cred)]:
        try:
            C.resolve_line(env=env, cred_path=cp)
            check("line refuses " + label, False, "no error")
        except C.LineConfigError:
            check("line refuses " + label, True)
    os.environ.pop("CE_NM_LINE", None)
    buf4 = io.StringIO()
    old = C.CRED_PATH
    C.CRED_PATH = os.path.join(d, "nope.json")
    with contextlib.redirect_stdout(buf4):
        rc4 = C.main(["--since", SINCE, "--state", state3], transcribe=transcriber(TEXTS))
    C.CRED_PATH = old
    check("main refuses with no line: rc 1, fixed phrase", rc4 == 1 and "no valid NM line" in buf4.getvalue(), buf4.getvalue())

    # ---- TwilioClient query, through a fake _get ----
    def query_ok(mod):
        calls = []
        cl2 = mod.TwilioClient(cred_path=cred, line=None)
        def fake_get(path, raw=False):
            calls.append(path)
            if "Calls.json" in path:
                return {"calls": [{"sid": "CA1"}]}
            return {"recordings": [{"sid": "RE9", "date_created": "Thu, 19 Nov 2026 15:00:10 +0000"}]}
        cl2._get = fake_get
        out = cl2.recordings_since(SINCE)
        q = urllib.parse.parse_qs(urllib.parse.urlparse(calls[0]).query)
        return (q.get("To") == [FAKE_LINE] and q.get("StartTime>") == ["2026-11-19"] and "Calls.json" in calls[0]
                and "CallSid=CA1" in calls[1] and out == [{"sid": "RE9", "created": "2026-11-19T15:00:10Z"}])
    os.environ.pop("CE_NM_LINE", None)
    check("Calls.json query: To = configured line, StartTime>, recordings by CallSid", query_ok(C))
    msrc = open(os.path.join(HERE, "..", "job", "call_code.py"), encoding="utf8").read()
    mut = "self.line = line or resolve_line(cred_path=cred_path)"
    check("mutation anchor present", mut in msrc)
    ns = {"__name__": "call_code_mut"}
    exec(compile(msrc.replace(mut, 'self.line = "+162****2578"'), "call_code_mut", "exec"), ns)
    class Mod: pass
    m = Mod(); m.TwilioClient = ns["TwilioClient"]
    check("mutation (masked constant) fails the query test", query_ok(m) is False)

# ---- round 3 mutations: each must change an extractor answer ----
_src = open(os.path.join(HERE, "..", "job", "call_code.py"), encoding="utf8").read()
def _mut_changes(old, new, probe, want):
    assert old in _src, old
    ns = {"__name__": "call_code_mut3"}
    exec(compile(_src.replace(old, new), "call_code_mut3", "exec"), ns)
    return ns["extract_code"](probe) != want
check("mutation (_unrepeat off) fails repeat test",
      _mut_changes("d = _unrepeat(after[0])", "d = after[0]", "Your verification code is 4 8 2 9 1 3. 4 8 2 9 1 3.", FAKE))
_narrow = r"(?<!zip )(?<!area )(?<!postal )(?<!promo )(?<!coupon )(?<!discount )(?:code|passcode|verification|pin|otp)"
check("mutation (wildcard cue back) fails compound-cue test",
      _mut_changes(_narrow, r"(?:\w*code|verification|pin|otp)", "the barcode reads 77889900", None))
check("mutation (lookbehinds off) fails zip-code test",
      _mut_changes(_narrow, r"(?:code|passcode|verification|pin|otp)", "my zip code is 37203", None))

# ---- CT label ----
check("heard label is CT", C._heard("2026-11-18T16:55:08Z") == "10:55 CT", C._heard("2026-11-18T16:55:08Z"))
check("heard label bad input", C._heard("junk") == "?")

# ---- fences ----
src = open(os.path.join(HERE, "..", "job", "call_code.py"), encoding="utf8").read()
check("no portal import", "import portal" not in src and "verify_bridge" not in src)
check("read-only toward Twilio (GET only)", "POST" not in src and "method=" not in src.replace("method=\"GET\"", ""))
check("no phone number in the module", not __import__("re").search(r"\+?\d{3}\W?\d{3}\W?\d{4}", src))

if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))); sys.exit(1)
print("call_code_test: all passed")
