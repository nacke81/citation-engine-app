"""CAPTCHA router tests (t_1c503c7f). Pure: saved-HTML snippets, no network, no browser."""
import os, sys, io, contextlib, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import captcha_route as C

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

KEY = "6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"
URL = "https://www.yellowpages.com/claim-your-listing"
V2 = '<form action="/claim"><input name="q"><div class="g-recaptcha" data-sitekey="%s"></div></form>' % KEY
V2_REV = '<form><div data-sitekey="%s" class="g-recaptcha"></div></form>' % KEY
V2_FRAME = '<form><iframe src="https://www.google.com/recaptcha/api2/anchor?ar=1&k=%s&co=x"></iframe></form>' % KEY
V3 = '<form><input name=a></form><script src="https://www.google.com/recaptcha/api.js?render=%s"></script>' % KEY
TS = '<form><input name=a><div class="cf-turnstile" data-sitekey="0x4AAAAAAABkMYinukE8nzYS"></div></form>'
HC = '<form><input name=a><div class="h-captcha" data-sitekey="10000000-ffff-ffff-ffff-000000000001"></div></form>'
IMG = '<form><input name=a><img src="/captcha.php?x=1" alt="captcha"><input name="code"></form>'
INTER = '<html><head><title>Just a moment...</title></head><body><div id="challenge-form"></div><script>window._cf_chl_opt={cvId:"3"}</script>Performing security verification</body></html>'
INTER_MENTIONS = '<html><head><title>Just a moment...</title></head><body><script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script><div class="cf-turnstile" data-sitekey="0x4AAAAAAABkMYinukE8nzYS"></div></body></html>'
NONE = "<html><body><form><input name=a></form></body></html>"

for name, html, typ, key in (("v2", V2, "recaptcha-v2", KEY), ("v2 attr order", V2_REV, "recaptcha-v2", KEY), ("v2 anchor iframe", V2_FRAME, "recaptcha-v2", KEY),
                             ("v3", V3, "recaptcha-v3", KEY), ("turnstile", TS, "turnstile", "0x4AAAAAAABkMYinukE8nzYS"), ("hcaptcha", HC, "hcaptcha", "10000000-ffff-ffff-ffff-000000000001"), ("image", IMG, "image", None)):
    d = C.detect(html, URL)
    check("D1 %s: type and sitekey" % name, not d["interstitial"] and len(d["widgets"]) == 1 and d["widgets"][0] == {"type": typ, "sitekey": key}, str(d))

for variant in (V2_FRAME.replace('&k=', '&amp;k='), V2_FRAME.replace('ar=1&k=', 'k='), V2_FRAME.replace('api2/anchor', 'enterprise/anchor').replace('&k=', '&amp;k=')):
    d = C.detect(variant, URL)
    check('B22 escaped/first/enterprise anchor', d['widgets'] == [{'type': 'recaptcha-v2', 'sitekey': KEY}], str(d))

d = C.detect(V3 + V2, URL)
check("D2 v3 key is not also reported as v2", [w["type"] for w in d["widgets"]] == ["recaptcha-v3"], str(d))

# interstitial vs widget
d = C.detect(INTER, URL)
check("I1 'Just a moment' page: interstitial, no widgets", d["interstitial"] and d["widgets"] == [], str(d))
p = C.plan(INTER, URL)
check("I2 interstitial plan = WALL:cloudflare-click, no CapSolver command", p["route"] == "park" and p["wall"] == "WALL:cloudflare-click" and p["commands"] == [], str(p))
d = C.detect(INTER_MENTIONS, URL)
check("I3 interstitial page that only loads turnstile.js is still an interstitial", d["interstitial"] and d["widgets"] == [], str(d))
check("I4 a real form with a turnstile widget is a widget, not an interstitial", C.detect(TS, URL)["widgets"][0]["type"] == "turnstile")

# commands
cmd = C.command({"type": "recaptcha-v2", "sitekey": KEY}, URL)
check("C1 v2 command exact", cmd == "node capsolver-cli.js --kind recaptcha-v2 --url %s --sitekey %s --cap 2" % (URL, KEY), cmd)
check("C1b v2 command never passes isInvisible", "isInvisible" not in cmd)
check("C2 turnstile command", C.command({"type": "turnstile", "sitekey": "0x4AAAAAAABkMYinukE8nzYS"}, URL).startswith("node capsolver-cli.js --kind turnstile "))
check("C3 v3 command", "--kind recaptcha-v3" in C.command({"type": "recaptcha-v3", "sitekey": KEY}, URL))
check("C4 image command carries the base64 body placeholder", "--kind image" in C.command({"type": "image", "sitekey": None}, URL) and "\"body\"" in C.command({"type": "image", "sitekey": None}, URL))
check("C5 custom cli path", C.command({"type": "turnstile", "sitekey": "0x4AAAAAAABkMYinukE8nzYS"}, URL, cli="C:/x/dist/src/capsolver-cli.js").startswith("node C:/x/dist/src/capsolver-cli.js "))
for bad, why in (({"type": "hcaptcha", "sitekey": "10000000-ffff-ffff-ffff-000000000001"}, "hcaptcha"), ({"type": "recaptcha-v2", "sitekey": None}, "no sitekey"),
                 ({"type": "recaptcha-v2", "sitekey": "a b; rm -rf /"}, "shell-unsafe sitekey")):
    try: C.command(bad, URL); raised = False
    except ValueError: raised = True
    check("C6 refused: %s" % why, raised)
try: C.command({"type": "turnstile", "sitekey": "0x4AAAAAAABkMYinukE8nzYS"}, "javascript:alert(1)"); raised = False
except ValueError: raised = True
check("C7 non-http url refused", raised)

# plans
p = C.plan(HC, URL)
check("P1 hcaptcha parks WALL:hcaptcha", p["route"] == "park" and p["wall"] == "WALL:hcaptcha" and p["commands"] == [], str(p))
p = C.plan(V2, URL)
check("P2 v2 routes to capsolver with 3 tries max", p["route"] == "capsolver" and p["max_tries"] == 3 and len(p["commands"]) == 1 and p["wall"] is None, str(p))
p = C.plan(IMG, URL)
check("P3 image routes to capsolver, 3 tries", p["route"] == "capsolver" and p["max_tries"] == 3)
p = C.plan(NONE, URL)
check("P4 no widget -> route none", p["route"] == "none" and p["commands"] == [])
p = C.plan(HC + V2.replace("<form", "<div"), URL)
check("P5 hcaptcha + v2 on one page: the supported one is routed, no wall", p["route"] == "capsolver" and p["wall"] is None, str(p))
check("P6 empty html -> none", C.plan("", URL)["route"] == "none")

# CLI
tmp = os.path.join(os.environ.get("TMPDIR") or os.environ.get("TEMP") or ".", "captcha_route_test.html")
open(tmp, "w", encoding="utf-8").write(V2)
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = C.main(["--url", URL, "--html", tmp])
out = json.loads(buf.getvalue())
check("M1 CLI prints the command and exits 0", rc == 0 and out["commands"][0].endswith("--cap 2"), buf.getvalue()[:120])
open(tmp, "w", encoding="utf-8").write(INTER)
with contextlib.redirect_stdout(io.StringIO()): rc = C.main(["--url", URL, "--html", tmp])
check("M2 CLI exits 3 for a parked wall", rc == 3)
os.remove(tmp)
check("M3 module never reads the CapSolver key", "CAPSOLVER_API_KEY" not in open(C.__file__, encoding="utf-8").read())

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
