"""CapSolver count tool tests (t_d13bd638). Run: python tests/count_capsolver_test.py (CI). No network: urlopen is poisoned; the balance call uses a fake opener."""
import os, sys, io, json, tempfile, shutil, urllib.request, contextlib
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import count_capsolver_builds as C

def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

TMP = tempfile.mkdtemp()
LOG = os.path.join(TMP, "solves.jsonl")
lines = [{"row": "create-2findlocal", "kind": "image", "ok": False, "cost": 0.001, "note": "wrong at 0.87"},
         {"row": "create-2findlocal", "kind": "image", "ok": True, "cost": 0.001},
         {"row": "create-cylex", "kind": "recaptcha-v2", "ok": True, "cost": 0.0008}]
open(LOG, "w", encoding="utf-8").write("# solve log\n" + "\n".join(json.dumps(l) for l in lines) + "\n\n")

solves = C.read_log(LOG)
check("C1 log reads, skipping comments and blank lines", len(solves) == 3)
s = C.summarize(solves, 10.0, 9.9972, 0.05)
check("C2 per-row counts", s["rows"]["create-2findlocal"]["solves"] == 2 and s["rows"]["create-2findlocal"]["accepted"] == 1 and s["rows"]["create-cylex"]["solves"] == 1)
check("C2 per-kind totals", s["kinds"]["image"]["solves"] == 2 and s["kinds"]["image"]["accepted"] == 1 and s["kinds"]["recaptcha-v2"]["solves"] == 1)
check("C2 logged cost is the sum", abs(s["logged_cost"] - 0.0028) < 1e-9, str(s["logged_cost"]))
check("C2 balance spend is before minus after", abs(s["balance_spend"] - 0.0028) < 1e-9, str(s["balance_spend"]))
check("C2 under the cap", not s["over_cap"])
check("C2 over the cap is flagged", C.summarize(solves, 10.0, 9.9, 0.05)["over_cap"])
check("C2 no balance: spend falls back to logged cost", C.summarize(solves)["spend"] == s["logged_cost"] and C.summarize(solves)["balance_spend"] is None)
r = C.render(s)
check("C3 render shows rows, kinds, balances and the cap", "create-2findlocal" in r and "wrong at 0.87" in r and "kind image" in r and "10.0000 before, 9.9972 after" in r and "cap 0.05: ok" in r)

for bad, why in (("not json\n", "not JSON"), ('{"kind": "image"}\n', "needs a row")):
    p = os.path.join(TMP, "bad.jsonl"); open(p, "w").write(bad)
    try: C.read_log(p); good = False
    except ValueError as e: good = why in str(e) and "line 1" in str(e)
    check("C4 bad log line is a clear error (%s)" % why, good)

def run(argv):
    buf, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        try: code = C.main(argv)
        except SystemExit as e: code = e.code
    return code, buf.getvalue()
code, out = run(["--log", LOG, "--before", "10.0", "--after", "9.9972", "--cap", "0.05"])
check("C5 CLI exit 0 and table when balance matches the log", code == 0 and "create-cylex" in out, str(code))
code, out = run(["--log", LOG, "--before", "10.0", "--after", "9.95", "--cap", "2"])
check("C5 CLI exit 1 on a balance/log mismatch (a solve missing from the log)", code == 1 and "MISMATCH" in out)
code, out = run(["--log", LOG, "--before", "10.0", "--after", "9.9972", "--cap", "0.001"])
check("C5 CLI exit 1 over the cap", code == 1 and "OVER" in out)
code, out = run(["--log", LOG, "--json"])
check("C5 --json parses", code == 0 and json.loads(out)["solves"] == 3)
code, _ = run(["--before", "10"])
check("C5 --before without --after is a usage error", code == 2)
code, _ = run([])
check("C5 no arguments is a usage error", code == 2)

# live balance: fake opener, key never printed
class R:
    def __init__(self, b): self.b = b
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return self.b
seen = {}
def opener(req, timeout=0):
    seen["body"] = json.loads(req.data); seen["url"] = req.full_url; return R(json.dumps({"errorId": 0, "balance": 9.9992}).encode())
check("C6 live balance parses the response", C.live_balance("SECRETKEY", opener) == 9.9992 and seen["url"].endswith("/getBalance") and seen["body"] == {"clientKey": "SECRETKEY"})
try: C.live_balance("k", lambda req, timeout=0: R(json.dumps({"errorId": 1, "errorCode": "ERROR_KEY_DENIED_ACCESS"}).encode())); good = False
except RuntimeError as e: good = "ERROR_KEY_DENIED_ACCESS" in str(e) and "k" != str(e)
check("C6 API error raises with the code", good)
envf = os.path.join(TMP, ".env"); open(envf, "w").write("OTHER=1\nCAPSOLVER_API_KEY=\"abc123\"\n")
check("C7 key read from env by name", C.api_key({"CAPSOLVER_API_KEY": "fromenv"}, ()) == "fromenv")
check("C7 key read from a .env file by name", C.api_key({}, (envf,)) == "abc123")
check("C7 no key is None", C.api_key({}, (os.path.join(TMP, "none.env"),)) is None)
os.environ.pop("CAPSOLVER_API_KEY", None)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    code = C.main(["--live-balance"], balance_fn=lambda: 9.5)
code2 = None
check("C7 --live-balance never prints the key", "abc123" not in buf.getvalue() and "fromenv" not in buf.getvalue())

shutil.rmtree(TMP, ignore_errors=True)
print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})"); sys.exit(0 if all(ok) else 1)
