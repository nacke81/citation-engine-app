"""Verify Now auto-allowlist on park (t_f31e2490). No network, no Chrome. Run: python tests/verify_allowlist_test.py (CI). Exit 1 on any failure."""
import hashlib, io, json, os, shutil, sys, tempfile, contextlib
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
TMP = tempfile.mkdtemp()
REPO_FILE = os.path.join(ROOT, "config", "verify_directories.json")
LOCAL = os.path.join(TMP, "outside", "verify_directories.local.json")
os.environ["CE_LOGS"] = os.path.join(TMP, "logs")
os.environ["CE_SITE_GUARD"] = os.path.join(TMP, "guard.json")
os.environ["CE_VERIFY_DIRECTORIES"] = os.path.join(HERE, "verify_directories_fixture.json")
os.environ["CE_VERIFY_DIRECTORIES_LOCAL"] = LOCAL
os.environ["CE_NO_CARDS"] = "1"
os.environ["CE_DIRECTORIES_WRITE"] = "0"
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json"); os.environ["CE_RUNS"] = tempfile.mkdtemp()
os.environ.pop("CE_SIGNIN_SEND_WRITE", None)
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, "job"))
import verify_fakes as F
import verify_bridge as B
import verify_send as S
import verify_allowlist as AL
import portal as P
import transitions as T
import yt_obs as YO

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (("  [%s]" % d) if d != "" else ""), flush=True)

def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
def local_rows():
    try: return json.load(open(LOCAL, encoding="utf-8"))["directories"]
    except Exception: return []

DAY = "2026-11-12"
SCC = P.ALLOWED["SCC"]
class FP:
    def __init__(self, domain): self.snap = {"found": 1, "directories": [{"name": domain, "domain": domain, "state": "live", "url": None, "urlKind": "search"}]}; self.calls = []
    def latest_snapshot(self, cid): return {"payload": json.loads(json.dumps(self.snap))}
    def upsert_snapshot(self, cid, day, payload): pass
    def call(self, method, path, body=None, prefer=None): self.calls.append((method, path, body))

def fresh(i=0, state="submitted"):
    p = os.path.join(TMP, "q%d.json" % i); shutil.copy(os.path.join(HERE, "fixtures", "test_queue.json"), p)
    q = json.load(open(p)); r = q["fix_queue"][i]; r["state"] = state; r["mike_approval"] = None; json.dump(q, open(p, "w"))
    return p, r["id"], r["directory"]

def park(i, vt, **kw):
    p, rid, d = fresh(i)
    fp = FP(d)
    r = T.record_transition("SCC", rid, "needs-human", "https://a.example/listing/1", "n", queue_path=p, today=DAY, portal=fp, verify_type=vt,
                            observation=YO.obs(vt, DAY), allowlist_path=kw.pop("allowlist_path", LOCAL), **kw)
    return r, rid, d, fp

repo0, fix0 = sha(REPO_FILE), sha(os.environ["CE_VERIFY_DIRECTORIES"])

# 1 sms park adds exactly one local entry with the required fields
r, rid, d, fp = park(0, "sms", vault_item="SCC - a.example login")
rows = local_rows()
check("1 sms park adds one local entry", r["allowlist"]["added"] is True and len(rows) == 1 and not r["errors"], r["errors"])
e = rows[0] if rows else {}
check("1b entry: send agent, channels [sms], vault item per tenant, added_by auto, row id, date",
      e.get("send") == "agent" and e.get("channels") == ["sms"] and e.get("vault_items") == {"SCC": "SCC - a.example login"} and e.get("added_by") == "auto" and e.get("row_id") == rid and e.get("added_on") == DAY and e.get("domain") == d, e)
check("1c the verification row was written in the same transition", r["verification_written"] is True and any(c[1].startswith("citation_verification") for c in fp.calls))

# 2 second park on the same directory (new row, same Directory) adds nothing
p2, rid2, d2 = fresh(0)
r2 = T.record_transition("SCC", rid2, "needs-human", "https://a.example/listing/1", "n", queue_path=p2, today=DAY, portal=FP(d2), verify_type="sms", observation=YO.obs("sms", DAY), allowlist_path=LOCAL, vault_item="other")
check("2 second park on the same directory is idempotent", r2["allowlist"]["added"] is False and len(local_rows()) == 1 and local_rows()[0]["vault_items"] == {"SCC": "SCC - a.example login"}, r2["allowlist"])

# 3 postcard park adds nothing; nor do other types at the helper
before = len(local_rows())
r3, _, _, _ = park(1, "postcard")
check("3 postcard park adds nothing", r3["allowlist"] is None and len(local_rows()) == before and not r3["errors"], r3["allowlist"])
res = [AL.auto_add("zzz.example", t, "SCC", "SCC - zzz", "x", DAY, path=LOCAL) for t in ("postcard", "id-check", "client-email", "document-upload")]
check("3b helper refuses postcard, id-check, client-email, document-upload", not any(x["added"] for x in res) and len(local_rows()) == before)

# 4 phone-call on a new directory adds with that channel
r4, _, d4, _ = park(1, "phone-call", vault_item="SCC - b item")
check("4 phone-call park adds a phone-call entry", r4["allowlist"]["added"] and [x for x in local_rows() if x["domain"] == d4][0]["channels"] == ["phone-call"])

# 5 no vault item passed: convention default, flagged
r5, _, d5, _ = park(2, "sms")
check("5 no --vault-item: convention default and flagged as defaulted", r5["allowlist"]["added"] and r5["allowlist"]["vault_item_defaulted"] is True and [x for x in local_rows() if x["domain"] == d5][0]["vault_items"] == {"SCC": "SCC - " + d5})

# 6 dry run adds nothing; the plan shows the request
pd, ridd, dd = fresh(3)
rd = T.record_transition("SCC", ridd, "needs-human", "https://a.example/listing/1", "n", queue_path=pd, today=DAY, portal=FP(dd), verify_type="sms", observation=YO.obs("sms", DAY), dry_run=True, allowlist_path=LOCAL)
check("6 dry run writes no allowlist entry", rd["allowlist_request"]["directory"] == dd and dd not in [x["domain"] for x in local_rows()])

# 7 a failed portal verification write adds nothing
class BadVer(FP):
    def call(self, method, path, body=None, prefer=None): raise RuntimeError("down")
pb, ridb, db = fresh(3)
rb = T.record_transition("SCC", ridb, "needs-human", "https://a.example/listing/1", "n", queue_path=pb, today=DAY, portal=FP(db), verification=BadVer(db), verify_type="sms", observation=YO.obs("sms", DAY), allowlist_path=LOCAL)
check("7 portal verification write failed: no allowlist entry", rb["verification_written"] is False and db not in [x["domain"] for x in local_rows()])

# 8 an injected fake without allowlist_path never touches the machine-wide file
os.environ.pop("CE_VERIFY_DIRECTORIES_LOCAL"); os.environ.pop("CE_VERIFY_DIRECTORIES")
real_default = AL.local_path()
os.environ["CE_VERIFY_DIRECTORIES"] = os.path.join(HERE, "verify_directories_fixture.json"); os.environ["CE_VERIFY_DIRECTORIES_LOCAL"] = LOCAL
p8, rid8, d8 = fresh(3)
r8 = T.record_transition("SCC", rid8, "needs-human", "https://a.example/listing/1", "n", queue_path=p8, today=DAY, portal=FP(d8), verify_type="sms", observation=YO.obs("sms", DAY))
check("8 test fake + no allowlist_path: no auto add", r8["allowlist"] is None and d8 not in [x["domain"] for x in local_rows()])
check("8b default local path is outside the repo", real_default and not AL._inside_repo(real_default), real_default)
try: AL.auto_add("q.example", "sms", "SCC", "SCC - q", "x", DAY, path=os.path.join(ROOT, "config", "x.local.json")); inside = False
except ValueError: inside = True
check("8c a path inside the repo is refused", inside and not os.path.exists(os.path.join(ROOT, "config", "x.local.json")))

# 9 merge: repo wins on conflict; local send=script is ignored
with open(LOCAL, "w", encoding="utf-8") as f:
    json.dump({"directories": [{"domain": "cylex.us", "channels": ["phone-call"], "send": "agent", "vault_items": {"SCC": "evil"}},
                               {"domain": "scr.example", "channels": ["sms"], "send": "script", "vault_items": {"SCC": "x"}},
                               {"domain": "ok.example", "channels": ["sms"], "send": "agent", "vault_items": {"SCC": "ok"}}]}, f)
m = {e["domain"]: e for e in B.load_directories()}
check("9 repo wins on conflict (cylex.us keeps repo channels/send/vault)", m["cylex.us"]["source"] == "repo" and m["cylex.us"]["channels"] == ["sms"] and m["cylex.us"]["vault_items"].get("SCC") == "SCC - cylex.us.com")
check("9b a local entry cannot name send=script; a valid one is merged", "scr.example" not in m and m["ok.example"]["source"] == "local")
check("9c explicit path reads that file only", [e["domain"] for e in B.load_directories(os.environ["CE_VERIFY_DIRECTORIES"])] == ["cylex.us", "agentdir.example"])

# 10 bridge: accepts the auto-added directory, refuses an unknown one with 0 site loads
os.unlink(LOCAL)
r10, _, d10, _ = park(0, "sms", vault_item="SCC - a.example login")
vp = F.StrictPortal(requests=[F.request(client=SCC)], verifications=[F.verification(client=SCC, directory=d10)])
verdict, _row = B.fence(F.request(client=SCC), vp)
check("10 bridge fence accepts the auto-added directory", verdict == "ok", verdict)
spawned = []
vp4 = F.StrictPortal(requests=[F.request(client=SCC)], verifications=[F.verification(client=SCC, directory=d10)])
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    rp = B.run_pass(vp4, B.VerifyRpc(vp4), F.NOW, lambda argv, **kw: spawned.append(argv) or object(), F.FakeCards())
check("10a bridge run_pass starts a send run for the auto-added directory", rp["started"] and rp["refused"] == [] and len(spawned) == 1, rp)
vp2 = F.StrictPortal(requests=[F.request(client=SCC, status="starting")], verifications=[F.verification(client=SCC, directory="unknown.example")])
verdict2, _ = B.fence(F.request(client=SCC), vp2)
check("10b bridge still refuses an unknown directory", verdict2 == "no_playbook", verdict2)
page = F.FakePage(); rt = F.FakeRuntime(page)
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    res = S.run(F.RID, vp2, B.VerifyRpc(vp2), rt, F.NOW)
check("10c unknown directory send run: failed/no_playbook, 0 site loads, 0 browsers, 0 vault fills", res == "failed:no_playbook" and page.visits == [] and rt.browsers == 0 and rt.vault_fills == 0, res)

# 11 --check lists both sources
vp3 = F.StrictPortal(requests=[], verifications=[])
lines = []
class CP:
    def call(self, *a, **k): return []
B.run_check(CP(), out=lines.append)
check("11 --check lists the repo and local sources", any("source repo" in x for x in lines) and any("source local" in x and LOCAL in x for x in lines), lines)

# 12 the tracked files are byte-identical after the whole run
check("12 repo allowlist file byte-identical", sha(REPO_FILE) == repo0)
check("12b fixture byte-identical", sha(os.environ["CE_VERIFY_DIRECTORIES"]) == fix0)

shutil.rmtree(TMP, ignore_errors=True)
print("\nALL PASS" if all(ok) else "\nFAILED", "(%d/%d)" % (sum(ok), len(ok))); sys.exit(0 if all(ok) else 1)
