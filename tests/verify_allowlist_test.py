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
r2 = T.record_transition("SCC", rid2, "needs-human", "https://a.example/listing/1", "n", queue_path=p2, today=DAY, portal=FP(d2), verify_type="sms", observation=YO.obs("sms", DAY), allowlist_path=LOCAL, vault_item="SCC - a.example login")
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

# 5 no --vault-item: the build run's own resolver decides; no convention guess (t_f31e2490 round 3)
import vault_item as VI
d5i = "5i.example"
r5, _, d5, _ = park(2, "sms", vault_items_lookup=[{"id": "1", "name": "SCC - " + VI.registrable(fresh(2)[2]) + ".com", "login": {"uris": []}}])
row5 = [x for x in local_rows() if x["domain"] == d5]
check("5a resolver hit: the entry carries the resolved item name", r5["allowlist"]["added"] and r5["allowlist"]["vault_item_resolved"] is True and row5 and list(row5[0]["vault_items"].values())[0].startswith("SCC - ") and list(row5[0]["vault_items"].values())[0].endswith(".com"), row5)
check("5b cylex shape: directory cylex.us resolves to SCC - cylex.us.com, never SCC - cylex.us", T._resolve_vault_item("cylex.us", [{"id": "9", "name": "SCC - cylex.us.com", "login": {"uris": []}}]) == "SCC - cylex.us.com")
nb = len(local_rows())
r5m, _, d5m, _ = park(3, "sms", vault_items_lookup=[])
check("5c resolver miss: nothing written, error line, park still wrote the verification row", r5m["allowlist"] is None if "allowlist" in r5m else True)
check("5c2 miss detail", "allowlist: vault item unresolved, pass --vault-item" in r5m["errors"] and len(local_rows()) == nb and d5m not in [x["domain"] for x in local_rows()] and r5m["verification_written"] is True, r5m["errors"])
amb = [{"id": "1", "name": "SCC - " + VI.registrable(fresh(4)[2]) + " a", "login": {"uris": []}}, {"id": "2", "name": "SCC - " + VI.registrable(fresh(4)[2]) + " b", "login": {"uris": []}}]
r5e, _, d5e, _ = park(4, "sms", vault_items_lookup=amb)
check("5d resolver error (ambiguous items): nothing written, park succeeds", "allowlist: vault item unresolved, pass --vault-item" in r5e["errors"] and d5e not in [x["domain"] for x in local_rows()] and r5e["verification_written"] is True, r5e["errors"])
check("5e the convention default is gone", not hasattr(T, "_default_vault_item"))
# 5f a wrong item on a LOCAL auto entry is corrected by a later explicit/resolved item; the repeat adds nothing
LOC5 = os.path.join(TMP, "outside5", "local.json")
w1 = AL.auto_add("fix5.example", "sms", "SCC", "SCC - fix5", "r1", DAY, path=LOC5)
w2 = AL.auto_add("fix5.example", "sms", "SCC", "SCC - fix5.example.com", "r2", DAY, path=LOC5)
w3 = AL.auto_add("fix5.example", "sms", "SCC", "SCC - fix5.example.com", "r3", DAY, path=LOC5)
rows5 = json.load(open(LOC5, encoding="utf-8"))["directories"]
check("5f wrong local item corrected once; repeat adds nothing; one entry", w1["added"] and w2["added"] and w2["kind"] == "merged" and not w3["added"] and len(rows5) == 1 and rows5[0]["vault_items"] == {"SCC": "SCC - fix5.example.com"}, [w2, w3, rows5])
# 5g a repo item is never replaced, and the repo file stays byte-identical
before5 = sha(os.environ["CE_VERIFY_DIRECTORIES"]); LOC5b = os.path.join(TMP, "outside5", "local-b.json")
rep = [e for e in B.load_directories() if e["vault_items"]][0]
tn, itm = list(rep["vault_items"].items())[0]
g = AL.auto_add(rep["domain"], rep["channels"][0], tn, itm + " DIFFERENT", "rg", DAY, path=LOC5b)
check("5g repo item never replaced: nothing written, file identical", g["added"] is False and not os.path.exists(LOC5b) and sha(os.environ["CE_VERIFY_DIRECTORIES"]) == before5, g)

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

# 13 merge on a listed Directory (review round 2): the bridge matches domain AND channel and the send needs vault_items[tenant]
LOCAL2 = os.path.join(TMP, "outside2", "verify_directories.local.json")
def local2(): 
    try: return json.load(open(LOCAL2, encoding="utf-8"))["directories"]
    except Exception: return []
_p1, _r1, dX = fresh(1)
FIX2 = os.path.join(TMP, "repo2.json")
with open(FIX2, "w", encoding="utf-8") as f:
    json.dump({"directories": [{"domain": dX, "channels": ["sms"], "send": "agent", "vault_items": {"NM": "NM - " + dX}},
                               {"domain": "scriptdir.example", "channels": ["sms"], "send": "script", "vault_items": {"NM": "NM - s"}}]}, f)
fix2_0 = sha(FIX2)
saved_dirs = os.environ["CE_VERIFY_DIRECTORIES"]; os.environ["CE_VERIFY_DIRECTORIES"] = FIX2
class _NoLocal: pass
# 13a cylex-like: a phone-call park on a repo Directory that lists sms only -> local supplement; bridge accepts phone-call; repo file untouched
r13, _, _, _ = park(1, "phone-call", vault_item="SCC - X item", allowlist_path=LOCAL2)
rows2 = local2()
check("13a phone-call park on a repo sms-only Directory writes one supplement row", r13["allowlist"]["added"] and r13["allowlist"]["kind"] == "supplement" and len(rows2) == 1 and rows2[0]["channels"] == ["phone-call"] and rows2[0]["vault_items"] == {"SCC": "SCC - X item"}, rows2)
os.environ["CE_VERIFY_DIRECTORIES_LOCAL"] = LOCAL2
m2 = {e["domain"]: e for e in B.load_directories()}
check("13b merged entry: repo channel kept, phone-call added, repo vault item kept, SCC item added, source repo, send agent",
      m2[dX]["channels"] == ["sms", "phone-call"] and m2[dX]["vault_items"] == {"NM": "NM - " + dX, "SCC": "SCC - X item"} and m2[dX]["send"] == "agent" and m2[dX]["source"] == "repo" and m2[dX].get("supplemented"))
v_pc = B.fence(F.request(client=SCC, channel="phone-call"), F.StrictPortal(requests=[F.request(client=SCC, channel="phone-call")], verifications=[F.verification(client=SCC, directory=dX)]))[0]
v_sms = B.fence(F.request(client=SCC, channel="sms"), F.StrictPortal(requests=[F.request(client=SCC)], verifications=[F.verification(client=SCC, directory=dX)]))[0]
check("13c bridge accepts a phone-call request (and still sms) for the supplemented Directory", v_pc == "ok" and v_sms == "ok", [v_pc, v_sms])
# 13d repeating the park adds nothing
rr, _, _, _ = park(1, "phone-call", vault_item="SCC - X item", allowlist_path=LOCAL2)
check("13d repeating the park adds nothing", rr["allowlist"]["added"] is False and len(local2()) == 1 and local2()[0]["vault_items"] == {"SCC": "SCC - X item"}, rr["allowlist"])
# 13e a repo-listed channel + tenant adds nothing
os.unlink(LOCAL2)
rn = AL.auto_add(dX, "sms", "NM", "x", "x", DAY, path=LOCAL2)
check("13e channel and tenant already in the repo entry: nothing written", rn["added"] is False and not os.path.exists(LOCAL2), rn)
# 13f a repo send=script entry is never extended
rs = AL.auto_add("scriptdir.example", "phone-call", "SCC", "SCC - s", "x", DAY, path=LOCAL2)
check("13f repo send=script entry is not extended", rs["added"] is False and not os.path.exists(LOCAL2) and "scriptdir.example" not in [e["domain"] for e in B.load_directories() if "phone-call" in e["channels"]], rs)
# 13g NM then SCC on one NEW directory: one local entry, both tenants, both pass; repeats add nothing
NEWD = "newdir.example"
a1 = AL.auto_add(NEWD, "sms", "NM", "NM - newdir", "r-nm", DAY, path=LOCAL2)
a2 = AL.auto_add(NEWD, "sms", "SCC", "SCC - newdir", "r-scc", DAY, path=LOCAL2)
rows3 = [e for e in local2() if e["domain"] == NEWD]
check("13g NM then SCC park: one entry, both tenants' vault items", a1["kind"] == "new" and a2["kind"] == "merged" and len(rows3) == 1 and rows3[0]["vault_items"] == {"NM": "NM - newdir", "SCC": "SCC - newdir"} and rows3[0]["channels"] == ["sms"], [a1, a2, rows3])
nm_v = B.fence(F.request(client=P.ALLOWED["NM"]), F.StrictPortal(requests=[F.request(client=P.ALLOWED["NM"])], verifications=[F.verification(client=P.ALLOWED["NM"], directory=NEWD)]))[0]
scc_v = B.fence(F.request(client=SCC), F.StrictPortal(requests=[F.request(client=SCC)], verifications=[F.verification(client=SCC, directory=NEWD)]))[0]
ent = B.directory_entry(NEWD, "sms")
check("13h both tenants' requests pass the fence and both have a vault item", nm_v == "ok" and scc_v == "ok" and ent["vault_items"].get("NM") and ent["vault_items"].get("SCC"), [nm_v, scc_v])
snap = open(LOCAL2, "rb").read()
b1 = AL.auto_add(NEWD, "sms", "NM", "NM - newdir", "r", DAY, path=LOCAL2); b2 = AL.auto_add(NEWD, "sms", "SCC", "SCC - newdir", "r", DAY, path=LOCAL2)
check("13i repeating either park adds nothing (file unchanged)", not b1["added"] and not b2["added"] and open(LOCAL2, "rb").read() == snap)
# 13j a later phone-call park on the new local entry adds the channel
a3 = AL.auto_add(NEWD, "phone-call", "SCC", "z", "r", DAY, path=LOCAL2)
check("13j a local entry gains a missing channel", a3["kind"] == "merged" and [e for e in local2() if e["domain"] == NEWD][0]["channels"] == ["sms", "phone-call"], a3)
# 13k --check lists the supplement
AL.auto_add(dX, "phone-call", "SCC", "SCC - X item", "r", DAY, path=LOCAL2)
lines2 = []
B.run_check(CP(), out=lines2.append)
check("13k --check lists supplements", any("supplements" in x and dX in x for x in lines2), lines2)
check("13l repo fixture 2 byte-identical", sha(FIX2) == fix2_0)
os.environ["CE_VERIFY_DIRECTORIES"] = saved_dirs; os.environ["CE_VERIFY_DIRECTORIES_LOCAL"] = LOCAL

# 12 the tracked files are byte-identical after the whole run
check("12 repo allowlist file byte-identical", sha(REPO_FILE) == repo0)
check("12b fixture byte-identical", sha(os.environ["CE_VERIFY_DIRECTORIES"]) == fix0)

shutil.rmtree(TMP, ignore_errors=True)
print("\nALL PASS" if all(ok) else "\nFAILED", "(%d/%d)" % (sum(ok), len(ok))); sys.exit(0 if all(ok) else 1)
