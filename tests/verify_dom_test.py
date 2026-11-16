"""Verify Now DOM landed check tests (t_00a83602). No network, no Chrome (CE_NO_CDP is set by verify_fakes), fake CDP DOM snapshots only.
Run: python tests/verify_dom_test.py (CI). `--mutations` runs only the mutation checks (each must be CAUGHT). Exit 1 on any failure."""
import contextlib, io, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp()
os.environ["CE_LOGS"] = os.path.join(TMP, "logs")
os.environ["CE_SITE_GUARD"] = os.path.join(TMP, "guard.json")
os.environ["CE_VERIFY_LOCKS"] = os.path.join(TMP, "locks")
os.environ["CE_VERIFY_DIRECTORIES"] = os.path.join(HERE, "verify_directories_fixture.json")
os.environ["CE_NO_CARDS"] = "1"
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json"); os.environ["CE_RUNS"] = tempfile.mkdtemp()
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "job"))
import verify_fakes as F
import verify_bridge as B
import verify_step as ST
import verify_dom as VD
import verify_scoreboard as SB
import portal as P

ONLY_MUT = "--mutations" in sys.argv
ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + ((" [%s]" % (d,)) if d != "" else ""), flush=True)

def quiet(fn, *a, **kw):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        r = fn(*a, **kw)
    return r, out.getvalue() + err.getvalue()

MASK = "(502) ***-0101"
AGENT_DIR = "agentdir.example"

def inp(**kw):
    d = {"type": "text", "autocomplete": "", "inputmode": "", "maxlength": None, "name": "", "id": "", "aria": "", "placeholder": "",
         "visible": True, "disabled": False, "readonly": False, "group": 1, "frame": 1}
    d.update(kw); return d

# one fixture per rule, each satisfying ONLY that rule
RULE_FIX = {
    "one_time_code": [inp(autocomplete="one-time-code", name="x1")],
    "numeric_maxlen": [inp(inputmode="numeric", maxlength="6", name="field1")],
    "named_code": [inp(name="verification_code")],
    "single_char_row": [inp(maxlength="1", group=7, name="d%d" % n) for n in range(6)],
}
NOT_CODE = {
    "empty page": [],
    "phone box": [inp(type="tel", name="phone", placeholder="Mobile number", inputmode="numeric", maxlength="10")],
    "zip box": [inp(inputmode="numeric", maxlength="5", name="zip")],
    "zipcode name": [inp(name="zipcode")],
    "promo code box": [inp(name="promo_code")],
    "country code": [inp(name="country_code", inputmode="numeric", maxlength="4")],
    "email box": [inp(type="email", name="email")],
    "submit button input": [inp(type="submit", name="verification_code")],
    "hidden code box": [inp(name="verification_code", visible=False)],
    "disabled code box": [inp(name="otp", disabled=True)],
    "readonly code box": [inp(name="otp", readonly=True)],
    "3 single-char boxes": [inp(maxlength="1", group=7) for _ in range(3)],
    "9 single-char boxes": [inp(maxlength="1", group=7) for _ in range(9)],
    "6 single-char boxes in 6 groups": [inp(maxlength="1", group=n) for n in range(6)],
    "numeric maxlength 3": [inp(inputmode="numeric", maxlength="3")],
    "numeric maxlength 12": [inp(inputmode="numeric", maxlength="12")],
}

if not ONLY_MUT:
    for name, snap in RULE_FIX.items():
        check("11a rule %s alone: a visible code input" % name, VD.has_code_input(snap) is True)
        only_this = {k: v for k, v in VD.RULES.items() if k == name}
        check("11a rule %s fixture is seen by that rule alone" % name, VD.has_code_input(snap, only_this) is True)
        for n2 in VD.RULES:
            if n2 != name: check("11a fixture %s is NOT seen by rule %s alone" % (name, n2), VD.has_code_input(snap, {n2: VD.RULES[n2]}) is False)
    for name, snap in NOT_CODE.items():
        check("11b not a code input: %s" % name, VD.has_code_input(snap) is False)
    check("11b one-time-code wins over an excluded word (explicit)", VD.has_code_input([inp(autocomplete="one-time-code", name="phone_otp")]))
    check("11b a code box in a second frame still counts", VD.has_code_input([inp(name="a", frame=1), inp(name="otp", frame=2)]))

# ---- step_sent over fake CDP
def portal_():
    return F.StrictPortal(requests=[F.request(status="starting", age_s=5, channel="sms")], verifications=[F.verification(directory=AGENT_DIR)])

CARD_STRINGS = ["Press the button to send your verification code", "Choose how to get your verification code",
                "Verify by text message: enter phone to receive a security code", "Sending verification code..."]
SIX_DIGIT = "A 6-digit code is on its way to your phone"

def run(text, snap, calls=None, check_fn=None):
    p = portal_()
    def fake_check(url, **kw):
        if calls is not None: calls.append(url)
        return VD.check(url, snap=lambda u: snap, sleep=lambda s: None, **kw)
    old = ST.DOM_CHECK; ST.DOM_CHECK = check_fn or fake_check
    try: r, out = quiet(ST.step_sent, F.RID, MASK, p, B.VerifyRpc(p), F.NOW, evidence=text)
    finally: ST.DOM_CHECK = old
    return r, p.requests[F.RID]["status"], out

if not ONLY_MUT:
    for t in CARD_STRINGS:
        r, st, out = run(t, NOT_CODE["phone box"])
        check("11c card string refused when the DOM shows no code input [%s]" % t[:36], r == ST.REFUSED and st == "starting", (r, st))
        check("11c ... and the log says why [%s]" % t[:36], "dom shows no visible code input" in out and "text said landed" in out, out.strip()[-120:])
        r, st, out = run(t, None, check_fn=lambda url: None)
        check("11d no CDP session: falls back to the text gate (today's behaviour, pinned) [%s]" % t[:36], r == 0 and st == "code_sent" and "dom unavailable" in out, (r, st))
        r, st, _ = run(t, RULE_FIX["named_code"])
        check("11e the same string with a visible code input records [%s]" % t[:36], r == 0 and st == "code_sent", (r, st))
    r, st, out = run(SIX_DIGIT, RULE_FIX["one_time_code"])
    check("11e '%s' records when the DOM shows a code input" % SIX_DIGIT, r == 0 and st == "code_sent", (r, st))
    r, st, out = run(SIX_DIGIT, [])
    check("11c ... and is refused with an empty DOM (text did not say landed)", r == ST.REFUSED and st == "starting" and "text did not say landed" in out, (r, st))
    r, st, out = run(SIX_DIGIT, None, check_fn=lambda url: None)
    check("11d no CDP: the text gate still refuses it (main did too)", r == ST.REFUSED and st == "starting", (r, st))
    def boom(url): raise RuntimeError("cdp exploded")
    r, st, out = run("Enter the verification code we texted you", None, check_fn=boom)
    check("11d a probe exception falls back to the text, nothing raised", r == 0 and st == "code_sent" and "dom check failed" in out, (r, st))
    for name, snap in RULE_FIX.items():
        r, st, _ = run("Enter the code we sent", snap)
        check("11e rule %s fixture records" % name, r == 0 and st == "code_sent", (r, st))
    # error evidence is decided before the DOM: a send refusal still fails the request even with a code input on the page
    r, st, _ = run("Enter the verification code. The number entered is not a mobile phone.", RULE_FIX["named_code"])
    check("11f a send refusal still ends failed/send_failed (DOM not consulted first)", st == "failed", (r, st))
    # the probe is asked for the tenant's own browser (NM 9334) and only when the client is known
    calls = []
    run("Enter the verification code", RULE_FIX["named_code"], calls=calls)
    check("11g the probe is given the NM tenant's loopback CDP url", calls == ["http://127.0.0.1:9334"], calls)
    check("11g an unknown client id has no browser", VD.tenant_cdp("00000000-0000-4000-8000-000000000000") is None and VD.tenant_cdp(None) is None)
    check("11g the SCC client maps to 9333", VD.tenant_cdp(P.ALLOWED["SCC"]) == "http://127.0.0.1:9333")
    # no-input page is re-read before it is refused; an unreadable browser is not retried
    n = []; res = VD.check("http://127.0.0.1:9334", snap=lambda u: (n.append(1), [])[1], sleep=lambda s: None)
    check("11h a no-input page is read 3 times then reads False", res is False and len(n) == 3, (res, len(n)))
    n = []; seq = iter([[], [], RULE_FIX["named_code"]])
    res = VD.check("http://127.0.0.1:9334", snap=lambda u: (n.append(1), next(seq))[1], sleep=lambda s: None)
    check("11h a code box that renders on the 3rd read counts", res is True and len(n) == 3, (res, len(n)))
    n = []; res = VD.check("http://127.0.0.1:9334", snap=lambda u: (n.append(1), None)[1], sleep=lambda s: None)
    check("11h an unreadable browser is None after one read", res is None and len(n) == 1, (res, len(n)))
    check("11h CE_NO_CDP makes the real probe return None without Playwright", VD.snapshot_inputs("http://127.0.0.1:9") is None)

# ---- mutations: every one must be caught
def caught(label, cond, d=""): check("12 MUTATION %s" % label, cond, d)

for name, snap in RULE_FIX.items():
    rules = {k: v for k, v in VD.RULES.items() if k != name}
    caught("rule %s removed: its fixture is refused, so 11a/11e catch it" % name, VD.has_code_input(snap, rules) is False)

orig_usable = VD._usable
VD._usable = lambda i: not i.get("disabled") and not i.get("readonly")
caught("visible check removed: the hidden code box is seen, so 11b catches it", VD.has_code_input(NOT_CODE["hidden code box"]) is True)
VD._usable = lambda i: bool(i.get("visible")) and not i.get("readonly")
caught("enabled check removed: the disabled code box is seen, so 11b catches it", VD.has_code_input(NOT_CODE["disabled code box"]) is True)
VD._usable = lambda i: bool(i.get("visible")) and not i.get("disabled")
caught("readonly check removed: the readonly code box is seen, so 11b catches it", VD.has_code_input(NOT_CODE["readonly code box"]) is True)
VD._usable = orig_usable

orig_nc = VD.NOT_A_CODE
VD.NOT_A_CODE = __import__("re").compile(r"(?!x)x")
caught("exclusion list removed: the phone, ZIP and promo boxes are seen, so 11b catches it",
       any(VD.has_code_input(NOT_CODE[k]) for k in ("phone box", "zip box", "promo code box", "country code", "zipcode name")))
VD.NOT_A_CODE = orig_nc

orig_rows = (VD.ROW_MIN, VD.ROW_MAX)
VD.ROW_MIN, VD.ROW_MAX = 1, 20
caught("row bounds widened to 1-20: 3 and 9 single-char boxes are seen, so 11b catches it",
       VD.has_code_input(NOT_CODE["3 single-char boxes"]) and VD.has_code_input(NOT_CODE["9 single-char boxes"]))
VD.ROW_MIN, VD.ROW_MAX = orig_rows

orig_texty = VD.TEXTY_TYPES
VD.TEXTY_TYPES = ("text", "tel", "number", "password", "search", "", "submit", "email", "hidden")
caught("type filter removed: a submit input named verification_code is seen, so 11b catches it", VD.has_code_input(NOT_CODE["submit button input"]) is True)
VD.TEXTY_TYPES = orig_texty

orig_pl = ST._page_landed
ST._page_landed = lambda rid, text, portal: ST.landed(text)   # DOM ignored
r, st, _ = run(CARD_STRINGS[0], NOT_CODE["phone box"])
caught("DOM ignored (text gate only): a card string records with no code input, so 11c catches it", st == "code_sent", (r, st))
r, st, _ = run(SIX_DIGIT, RULE_FIX["named_code"])
caught("DOM ignored (text gate only): the six-digit string is refused with a code input on the page, so 11e catches it", st == "starting", (r, st))
ST._page_landed = orig_pl

orig_chk = VD.check
def lenient(url, **kw): return None if orig_chk(url, snap=lambda u: NOT_CODE["phone box"], sleep=lambda s: None) is False else True
r, st, _ = run(CARD_STRINGS[0], None, check_fn=lenient)
caught("a no-input page treated as 'cannot see': the card string records, so 11c catches it", st == "code_sent", (r, st))
seq = iter([[], RULE_FIX["named_code"]])
caught("re-read count cut to 1: a late code box is missed (11h expects True at 3 reads)", orig_chk("u", snap=lambda u: next(seq), sleep=lambda s: None, reads=1) is False)

print("\n%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
