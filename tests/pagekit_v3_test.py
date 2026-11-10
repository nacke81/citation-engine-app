"""reCAPTCHA v3 pageAction + logged CLI wrapper (t_bc10b2d3).
No network, no browser, no real CapSolver, no .env: fake CLI runner, fake page, temp log files; the injected JS runs in node against a stub DOM."""
import io, json, os, subprocess, sys, tempfile, types
HERE = os.path.dirname(os.path.abspath(__file__))
JOB = os.path.join(HERE, "..", "job")
sys.path.insert(0, JOB)
import urllib.request
def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net
import pagekit as PK, captcha_route as CR, capsolver_solve as CS

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

TMP = tempfile.mkdtemp()
KEY = "6LcoNgorAAAAAMRnkJocLrh2KX4Z3AquTzRin2Et"
URL = "https://www.findcarez.com/signup"
V3_HTML = ('<script src="https://www.google.com/recaptcha/api.js?render=%s"></script><form>'
           '<input type="hidden" name="g-recaptcha-response"></form>'
           "<script>grecaptcha.ready(function(){grecaptcha.execute('%s', {action: 'register'}).then(function(t){});});</script>") % (KEY, KEY)
V3_NO_ACTION = '<script src="https://www.google.com/recaptcha/api.js?render=%s"></script><form></form>' % KEY
V2_HTML = '<div class="g-recaptcha" data-sitekey="6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"></div>'
GOOD = {"ok": True, "solution": {"gRecaptchaResponse": "TOKEN-V3"}, "cost": 0.003}

class Proc:
    def __init__(self, out): self.stdout, self.returncode = out, 0
class Runner:
    def __init__(self, outs): self.outs, self.calls = list(outs), []
    def __call__(self, cmd, **k):
        self.calls.append(cmd); o = self.outs.pop(0)
        return Proc(json.dumps(o) if isinstance(o, dict) else o)
class Page:
    def __init__(self, html, url=URL): self.html, self.url, self.js = html, url, []
    def content(self): return self.html
    def evaluate(self, script, arg=None):
        self.js.append(script)
        if script is PK.INJECT_TOKEN_JS: return {"fields": 2, "callbacks": 0}
        if script is PK.V3_EXECUTE_JS: return 1
        return None
def extra_of(cmd): return json.loads(cmd[cmd.index("--extra") + 1]) if "--extra" in cmd else None
def rows(p): return [json.loads(l) for l in open(p, encoding="utf-8")] if os.path.exists(p) else []

# 1 pageAction reaches the CLI request (explicit)
lg = os.path.join(TMP, "a.jsonl"); r = Runner([GOOD]); pg = Page(V3_NO_ACTION)
out = PK.solve_and_inject(pg, "create-findcarez", runner=r, log_path=lg, page_action="register")
check("V1 explicit page_action reaches the CLI as --extra pageAction", extra_of(r.calls[0]) == {"pageAction": "register"}, str(r.calls[0]))
check("V1 CLI argv is the v3 kind with the sitekey", r.calls[0][r.calls[0].index("--kind") + 1] == "recaptcha-v3" and KEY in r.calls[0])
check("V1 result reports the action and v3 inject ran", out["page_action"] == "register" and PK.V3_EXECUTE_JS in pg.js, str(out))

# 2 auto-detect from the page
lg = os.path.join(TMP, "b.jsonl"); r = Runner([GOOD]); pg = Page(V3_HTML)
out = PK.solve_and_inject(pg, "create-findcarez", runner=r, log_path=lg)
check("V2 action auto-detected from grecaptcha.execute(key, {action})", extra_of(r.calls[0]) == {"pageAction": "register"} and out["page_action"] == "register", str(r.calls[0]))
check("V2 detect_page_action: none when absent", PK.detect_page_action(V3_NO_ACTION) is None and PK.detect_page_action("") is None)
lg = os.path.join(TMP, "b2.jsonl"); r = Runner([GOOD])
PK.solve_and_inject(Page(V3_HTML), "create-x", runner=r, log_path=lg, page_action="override")
check("V2 explicit page_action beats the detected one", extra_of(r.calls[0]) == {"pageAction": "override"})
lg = os.path.join(TMP, "b3.jsonl"); r = Runner([GOOD])
out = PK.solve_and_inject(Page(V3_NO_ACTION), "create-x", runner=r, log_path=lg)
check("V2 no action known => no --extra (old behaviour kept)", extra_of(r.calls[0]) is None and out["page_action"] is None)

# 3 v2 never gets pageAction
lg = os.path.join(TMP, "c.jsonl"); r = Runner([{"ok": True, "solution": {"gRecaptchaResponse": "T2"}}]); pg = Page(V2_HTML)
out = PK.solve_and_inject(pg, "create-v2", runner=r, log_path=lg, page_action="register")
check("V3 recaptcha-v2 ignores page_action; no v3 override evaluated", extra_of(r.calls[0]) is None and "page_action" not in out and PK.V3_EXECUTE_JS not in pg.js, str(out))

# 4 real JS in node against a stub DOM: every response field set, execute resolves to the token
NODE_STUB = """
const fields = [{value:'', dispatchEvent(){}}, {value:'', dispatchEvent(){}}, {value:'', dispatchEvent(){}}];
global.Event = function(){};
global.document = {querySelectorAll: () => ({forEach: (f) => fields.forEach(f)})};
global.window = global; window.___grecaptcha_cfg = {};
window.grecaptcha = {execute: () => Promise.resolve('FRESH'), enterprise: {execute: () => Promise.resolve('FRESH-E')}};
const inject = %s, v3 = %s;
const r = inject('TOK'); const n = v3('TOK');
Promise.all([grecaptcha.execute('k', {action: 'register'}), grecaptcha.enterprise.execute('k', {action: 'register'})]).then(t =>
  console.log(JSON.stringify({r, n, values: fields.map(f => f.value), exec: t})));
""" % (PK.INJECT_TOKEN_JS, PK.V3_EXECUTE_JS)
try:
    p = subprocess.run(["node", "-e", NODE_STUB], capture_output=True, text=True, timeout=30)
    res = json.loads(p.stdout.strip().splitlines()[-1])
except Exception as e:
    res = {"err": str(e)}
check("V4 v3 inject: all 3 response fields hold the token", res.get("values") == ["TOK"] * 3 and res.get("r", {}).get("fields") == 3, str(res))
check("V4 v3 inject: grecaptcha.execute and .enterprise.execute resolve to the token", res.get("exec") == ["TOK", "TOK"] and res.get("n") == 2, str(res))

# 5 inject_token(v3) with no field and no callback still counts execute override; nothing at all raises
class Bare(Page):
    def evaluate(self, script, arg=None): return {"fields": 0, "callbacks": 0} if script is PK.INJECT_TOKEN_JS else 0
try: PK.inject_token(Bare(V3_HTML), "T", v3=True); raised = False
except PK.CaptchaError: raised = True
check("V5 nowhere to put the token still raises CaptchaError", raised)

# 6 solve-and-inject logs one line per call; failure logs ok=false
lg = os.path.join(TMP, "d.jsonl"); r = Runner([{"ok": False, "reason": "ERROR_INVALID_TASK_DATA"}])
try: PK.solve_and_inject(Page(V3_HTML), "create-f", runner=r, log_path=lg); raised = False
except PK.CaptchaError: raised = True
l = rows(lg)
check("V6 failed pagekit solve raises and writes one ok=false line", raised and len(l) == 1 and l[0]["ok"] is False and l[0]["kind"] == "recaptcha-v3" and l[0]["row"] == "create-f" and "INVALID" in l[0]["note"], str(l))

# 7 CLI wrapper: success writes exactly one line with row/kind/ok/cost/note
lg = os.path.join(TMP, "e.jsonl"); r = Runner([GOOD]); buf = io.StringIO()
rc = CS.main(["--row", "create-findcarez", "--kind", "recaptcha-v3", "--url", URL, "--sitekey", KEY, "--page-action", "register"], runner=r, log_path=lg, out=buf)
l = rows(lg); o = json.loads(buf.getvalue())
check("W1 CLI wrapper solve: exit 0, token printed, pageAction sent", rc == 0 and o["ok"] and o["solution"]["gRecaptchaResponse"] == "TOKEN-V3" and extra_of(r.calls[0]) == {"pageAction": "register"})
check("W1 exactly one log line with row, kind, ok, cost, note", len(l) == 1 and l[0] == {"row": "create-findcarez", "kind": "recaptcha-v3", "ok": True, "cost": 0.003, "note": ""}, str(l))

# 8 CLI wrapper failure -> ok=false line, exit 2
lg = os.path.join(TMP, "f.jsonl"); r = Runner([{"ok": False, "reason": "ERROR_ZERO_BALANCE"}]); buf = io.StringIO()
rc = CS.main(["--row", "create-findcarez", "--kind", "recaptcha-v3", "--url", URL, "--sitekey", KEY], runner=r, log_path=lg, out=buf)
l = rows(lg); o = json.loads(buf.getvalue())
check("W2 failed CLI solve: exit 2, ok=false printed, one ok=false log line with the reason", rc == 2 and o["ok"] is False and len(l) == 1 and l[0]["ok"] is False and "ZERO_BALANCE" in l[0]["note"], str(l))
lg = os.path.join(TMP, "g.jsonl"); r = Runner(["not json at all"]); buf = io.StringIO()
rc = CS.main(["--row", "z", "--kind", "turnstile", "--url", URL, "--sitekey", "0x4AAAAAAAxxxxxxxxxxxx"], runner=r, log_path=lg, out=buf)
l = rows(lg)
check("W2 unparseable CLI output is logged ok=false too", rc == 2 and len(l) == 1 and l[0]["ok"] is False, str(l))

# 9 wrapper guards: page-action on non-v3; the per-row cap holds across calls; missing CLI logs nothing
buf = io.StringIO(); lg = os.path.join(TMP, "h.jsonl"); r = Runner([])
rc = CS.main(["--row", "z", "--kind", "recaptcha-v2", "--url", URL, "--sitekey", KEY, "--page-action", "x"], runner=r, log_path=lg, out=buf)
check("W3 --page-action on a non-v3 kind is refused, no CLI call, no log", rc == 2 and not r.calls and not os.path.exists(lg))
lg = os.path.join(TMP, "i.jsonl")
for _ in range(3):
    CS.main(["--row", "cap", "--kind", "recaptcha-v3", "--url", URL, "--sitekey", KEY], runner=Runner([{"ok": False, "reason": "ERROR_CAPTCHA_SOLVE_FAILED"}] * 3), log_path=lg, out=io.StringIO())
r = Runner([GOOD]); rc = CS.main(["--row", "cap", "--kind", "recaptcha-v3", "--url", URL, "--sitekey", KEY], runner=r, log_path=lg, out=io.StringIO())
check("W3 per-row cap of 3 calls holds across wrapper runs (4th makes no call)", rc == 2 and not r.calls and len(rows(lg)) == 3, str(len(rows(lg))))

# 10 router: extra no longer image-only
cmd = CR.argv({"type": "recaptcha-v3", "sitekey": KEY}, URL, cli="cli.js", extra={"pageAction": "register"})
check("R1 captcha_route.argv passes --extra for v3", cmd[-3:-1] == ["--extra", '{"pageAction": "register"}'] or extra_of(cmd) == {"pageAction": "register"}, str(cmd))
check("R1 no extra => no --extra flag", "--extra" not in CR.argv({"type": "recaptcha-v3", "sitekey": KEY}, URL, cli="cli.js"))

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
