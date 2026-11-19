"""call_code tests (t_262cb861). Fake Twilio client, fake transcriber, fake digits only. No network, no whisper, no portal, no real code.
Run: python tests/call_code_test.py   exit 1 on any failure
"""
import contextlib, io, json, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import call_code as C

FAILS = []


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
    ("too short", "press 12 now", None),
    ("too long", "reference 123456789012", None),
    ("none", "Hello, please leave a message.", None),
    ("empty", "", None),
    ("None", None, None),
]:
    got = C.extract_code(text)
    check("extract " + label, got == want, "got %r" % (got,))

# ---- run_once ----
RECS = [
    {"sid": "RE0001", "created": "2026-11-19T15:00:10Z", "from_masked": "+*******7298"},
    {"sid": "RE0002", "created": "2026-11-19T15:30:10Z", "from_masked": "+*******7298"},
    {"sid": "RE0000", "created": "2026-11-18T01:00:00Z", "from_masked": "+*******7298"},   # before since
]
TEXTS = {"RE0001": "Your code is four eight two nine one three. Again: 482913.", "RE0002": "Thank you for calling. Goodbye."}
with tempfile.TemporaryDirectory() as d:
    state = os.path.join(d, "state.json")
    cl = FakeClient(RECS)
    lines = C.run_once(cl, transcriber(TEXTS), state, "2026-11-19T00:00:00Z")
    check("two new -> two lines", len(lines) == 2, lines)
    check("code line has code", any("482913" in l and "call code" in l for l in lines), lines)
    check("no-code line says so", any("no code found" in l and "482913" not in l for l in lines), lines)
    check("old recording not fetched", "RE0000" not in cl.fetched, cl.fetched)
    check("no recording URL in a line", not any("http" in l for l in lines), lines)
    raw = open(state, encoding="utf8").read()
    check("state has no code", "482913" not in raw and "four eight" not in raw, raw)
    check("state has sids", "RE0001" in raw and "RE0002" in raw, raw)
    check("second pass silent", C.run_once(cl, transcriber(TEXTS), state, "2026-11-19T00:00:00Z") == [])

    # transcriber failure: one safe line, NOT marked seen, retried next pass
    state2 = os.path.join(d, "state2.json")
    boom = {"RE0001": RuntimeError("whisper died with 482913 in the message"), "RE0002": "ok"}
    l1 = C.run_once(FakeClient(RECS[:1]), transcriber(boom), state2, "2026-11-19T00:00:00Z")
    check("failure one line", len(l1) == 1 and "could not transcribe" in l1[0], l1)
    check("failure never echoes exception text", "482913" not in l1[0] and "whisper" not in l1[0], l1)
    check("failure not marked seen", "RE0001" not in (open(state2).read() if os.path.exists(state2) else ""))
    l2 = C.run_once(FakeClient(RECS[:1]), transcriber(TEXTS), state2, "2026-11-19T00:00:00Z")
    check("retry succeeds", len(l2) == 1 and "482913" in l2[0], l2)

    # stdout/log: main() prints lines only, never writes the code elsewhere
    buf = io.StringIO()
    state3 = os.path.join(d, "state3.json")
    with contextlib.redirect_stdout(buf):
        rc = C.main(["--since", "2026-11-19T00:00:00Z", "--state", state3], client=FakeClient(RECS[:1]), transcribe=transcriber(TEXTS))
    check("main rc 0", rc == 0, rc)
    check("main prints code line", "482913" in buf.getvalue(), buf.getvalue())
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        rc2 = C.main(["--since", "2026-11-19T00:00:00Z", "--state", state3], client=FakeClient(RECS[:1]), transcribe=transcriber(TEXTS))
    check("main empty when nothing new", rc2 == 0 and buf2.getvalue() == "", buf2.getvalue())
    # reader failure: fixed phrase, rc 1, no exception text
    class Dead:
        def recordings_since(self, s): raise RuntimeError("secret 482913")
    buf3 = io.StringIO()
    with contextlib.redirect_stdout(buf3):
        rc3 = C.main(["--since", "2026-11-19T00:00:00Z", "--state", state3], client=Dead(), transcribe=transcriber(TEXTS))
    check("main failure rc 1 fixed phrase", rc3 == 1 and "482913" not in buf3.getvalue() and "failed" in buf3.getvalue(), buf3.getvalue())

# ---- fences ----
src = open(os.path.join(HERE, "..", "job", "call_code.py"), encoding="utf8").read()
check("no portal import", "import portal" not in src and "verify_bridge" not in src)
check("read-only toward Twilio (GET only)", "POST" not in src and "method=" not in src.replace("method=\"GET\"", ""))

if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))); sys.exit(1)
print("call_code_test: all passed")
