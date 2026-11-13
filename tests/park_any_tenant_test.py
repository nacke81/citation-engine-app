"""Park works for any tenant, NM first (t_cb7bad04). No network, no Chrome, no prod. Run: python tests/park_any_tenant_test.py (CI). Exit 1 on any failure."""
import hashlib, io, json, os, shutil, sys, tempfile, contextlib
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
TMP = tempfile.mkdtemp()
LOCAL = os.path.join(TMP, "outside", "verify_directories.local.json")
os.environ["CE_LOGS"] = os.path.join(TMP, "logs")
os.environ["CE_SITE_GUARD"] = os.path.join(TMP, "guard.json")
os.environ["CE_VERIFY_DIRECTORIES"] = os.path.join(HERE, "verify_directories_fixture.json")
os.environ["CE_VERIFY_DIRECTORIES_LOCAL"] = LOCAL
os.environ["CE_NO_CARDS"] = "1"
os.environ["CE_DIRECTORIES_WRITE"] = "0"
os.environ["CE_ACTIVITIES_WRITE"] = "1"
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json"); os.environ["CE_RUNS"] = tempfile.mkdtemp()
os.environ.pop("CE_SIGNIN_SEND_WRITE", None)
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, "job"))
import portal as P
import transitions as T
import yt_obs as YO

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + ((" [%s]" % d) if d != "" else ""), flush=True)

DAY = "2026-11-13"
SLUG = "na" + "cke-media"
NM, SCC = P.ALLOWED["NM"], P.ALLOWED["SCC"]

class FP:
    """Portal fake: records every call and every snapshot write."""
    def __init__(self, domain="a.example"): self.calls = []; self.snaps = []; self.domain = domain
    def latest_snapshot(self, cid): return {"payload": {"found": 1, "directories": [{"name": self.domain, "domain": self.domain, "state": "live", "url": None, "urlKind": "search"}]}}
    def upsert_snapshot(self, cid, day, payload): self.snaps.append(cid)
    def call(self, method, path, body=None, prefer=None): self.calls.append((method, path, body))

def nm_queue(name="nm-fix-queue.json", rows=None):
    d = tempfile.mkdtemp(dir=TMP); p = os.path.join(d, name)
    rows = rows or [{"id": "nm-fix-mapquest", "directory": "mapquest.com", "kind": "fix", "state": "needs-human", "mike_approval": None, "history": [{"date": "2026-11-11", "change": "queued"}]},
                    {"id": "nm-fix-bbb", "directory": "bbb.org", "kind": "fix", "state": "queued", "mike_approval": None, "history": []}]
    json.dump({"business": "NM fixture", "fix_queue": rows}, open(p, "w")); return p

def scc_queue():
    p = os.path.join(tempfile.mkdtemp(dir=TMP), "scc-q.json"); shutil.copy(os.path.join(HERE, "fixtures", "test_queue.json"), p)
    q = json.load(open(p)); r = q["fix_queue"][0]; r["state"] = "submitted"; r["mike_approval"] = None; json.dump(q, open(p, "w"))
    return p, r["id"], r["directory"]

def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
def refused(fn):
    try: fn(); return None
    except T.TransitionRefused as e: return str(e)
def local_rows():
    try: return json.load(open(LOCAL, encoding="utf-8"))["directories"]
    except Exception: return []
def ver_posts(fp): return [c for c in fp.calls if c[1].startswith("citation_verification")]

def nm_park(p, rid="nm-fix-mapquest", vt="phone-call", fp=None, **kw):
    fp = fp or FP("mapquest.com")
    kw.setdefault("allowlist_path", LOCAL); kw.setdefault("vault_item", "NM - mapquest.com login")
    r = T.record_transition("NM", rid, "needs-human", None, "n", queue_path=p, today=DAY, portal=fp, verify_type=vt, observation=YO.obs(vt, DAY), reason_code="phone_verify", **kw)
    return r, fp

# 1 NM phone-call park: queue + one citation_verification row for the NM client + allowlist entry (tenant NM) + no SCC snapshot / activity
p = nm_queue(); r, fp = nm_park(p)
posts = ver_posts(fp)
check("1 NM park writes no errors", not r["errors"], r["errors"])
check("1b one citation_verification POST for the NM client id, verify type phone-call", len(posts) == 1 and posts[0][2][0]["client_id"] == NM and posts[0][2][0]["verification_type"] == "phone-call" and posts[0][2][0]["directory"] == "mapquest.com" and r["verification_written"] is True, posts)
check("1c nothing carries the SCC client id", not any(SCC in json.dumps(c) for c in fp.calls) and fp.snaps == [], fp.calls)
check("1d tenant slug (NM portal slug) in the result; portal snapshot skipped; no activity", r["tenant"]["slug"] == SLUG and r["tenant"]["client_id"] == NM and r["portal_written"] == "skipped" and r["activities_written"] is False and not any("deliverables" in c[1] for c in fp.calls))
e = [x for x in local_rows() if x["domain"] == "mapquest.com"]
check("1e allowlist entry: phone-call, vault item under tenant NM, row id", len(e) == 1 and e[0]["channels"] == ["phone-call"] and e[0]["vault_items"] == {"NM": "NM - mapquest.com login"} and e[0]["row_id"] == "nm-fix-mapquest", e)
q = json.load(open(p)); row = q["fix_queue"][0]
check("1f queue row stays needs-human with a verify_type history entry; old history kept; backup written; other row untouched",
      row["state"] == "needs-human" and row["history"][0] == {"date": "2026-11-11", "change": "queued"} and row["history"][-1].get("verify_type") == "phone-call" and row["history"][-1].get("reason_code") == "phone_verify" and os.path.exists(p + ".bak-nm-" + DAY) and q["fix_queue"][1]["state"] == "queued")

# 2 resolved vault item (no --vault-item): resolve_for_domain result is used; unresolved = error, no entry
import vault_item as V
orig = V.resolve_for_domain
V.resolve_for_domain = lambda d, items=None: (None, "NM - %s resolved" % d)
try: r2, fp2 = nm_park(nm_queue(), vault_item=None, allowlist_path=os.path.join(TMP, "outside", "l2.json"))
finally: V.resolve_for_domain = orig
l2 = json.load(open(os.path.join(TMP, "outside", "l2.json")))["directories"]
check("2 allowlist uses vault_item.resolve_for_domain when no --vault-item", r2["allowlist"]["added"] and l2[0]["vault_items"] == {"NM": "NM - mapquest.com resolved"} and r2["allowlist"]["vault_item_resolved"] is True, r2["allowlist"])

# 3 sms park on a second NM row; postcard adds no allowlist; row without a verify step unaffected
p3 = nm_queue(); r3, fp3 = nm_park(p3, rid="nm-fix-bbb", vt="sms", vault_item="NM - bbb.org login", fp=FP("bbb.org"))
check("3 NM sms park from queued: verification row + allowlist", r3["verification_written"] and r3["allowlist"]["added"] and ver_posts(fp3)[0][2][0]["verification_type"] == "sms" and json.load(open(p3))["fix_queue"][1]["state"] == "needs-human", r3["errors"])

# 4 dry run prints the exact portal write and writes nothing
p4 = nm_queue(); h = sha(p4); n_local = len(local_rows()); fp4 = FP("mapquest.com")
r4 = T.record_transition("NM", "nm-fix-mapquest", "needs-human", None, "n", queue_path=p4, today=DAY, portal=fp4, verify_type="phone-call", observation=YO.obs("phone-call", DAY), reason_code="phone_verify", dry_run=True, allowlist_path=LOCAL)
vr = r4["verification_request"]
check("4 dry run: exact citation_verification upsert for the NM client, allowlist plan, snapshot skipped",
      vr["method"] == "POST" and vr["path"] == T.VERIFY_UPSERT_PATH and vr["body"][0]["client_id"] == NM and vr["body"][0]["verification_type"] == "phone-call"
      and r4["allowlist_request"]["tenant"] == "NM" and r4["tenant"]["slug"] == SLUG and str(r4["portal_request"]).startswith("skipped"), r4["verification_request"])
check("4b dry run wrote nothing (queue identical, no calls, no allowlist, no backup)", sha(p4) == h and fp4.calls == [] and len(local_rows()) == n_local and not os.path.exists(p4 + ".bak-nm-" + DAY))

# 5 TENANT LOCK, NM -> SCC: an NM park cannot write an SCC row, nor an SCC queue file
sp, srid, sdir = scc_queue(); hs = sha(sp); fpa = FP(sdir)
m1 = refused(lambda: T.record_transition("NM", srid, "needs-human", None, "n", queue_path=sp, today=DAY, portal=fpa, verify_type="sms", observation=YO.obs("sms", DAY), allowlist_path=LOCAL, vault_item="x"))
check("5 NM park on an SCC row id refused before any write", m1 and "tenant lock" in m1 and sha(sp) == hs and fpa.calls == [], m1)
pnm = nm_queue(name="scc-fix-create-queue.json"); fpb = FP("mapquest.com")
m2 = refused(lambda: T.record_transition("NM", "nm-fix-mapquest", "needs-human", None, "n", queue_path=pnm, today=DAY, portal=fpb, verify_type="sms", observation=YO.obs("sms", DAY), allowlist_path=LOCAL, vault_item="x"))
check("5b NM park pointed at a non-NM queue file refused", m2 and "tenant lock" in m2 and fpb.calls == [], m2)

# 6 TENANT LOCK, SCC -> NM: an SCC park cannot write an nm- row
pn = nm_queue(); hn = sha(pn); fpc = FP("mapquest.com")
m3 = refused(lambda: T.record_transition("SCC", "nm-fix-mapquest", "needs-human", None, "n", queue_path=pn, today=DAY, portal=fpc, verify_type="sms", observation=YO.obs("sms", DAY), allowlist_path=LOCAL, vault_item="x"))
check("6 SCC park on an nm- row refused before any write", m3 and "tenant lock" in m3 and sha(pn) == hn and fpc.calls == [], m3)
check("6b unknown client refused (no tenant config)", "no tenant config" in (refused(lambda: T.record_transition("ZZZ", "x", "needs-human", None, "n", queue_path=pn)) or ""))

# 7 SCC behavior unchanged: same park still writes the SCC client id, snapshot overlay, backup-free
sp7, srid7, sdir7 = scc_queue(); fp7 = FP(sdir7)
r7 = T.record_transition("SCC", srid7, "needs-human", "https://a.example/listing/1", "n", queue_path=sp7, today=DAY, portal=fp7, verify_type="sms", observation=YO.obs("sms", DAY), allowlist_path=LOCAL, vault_item="SCC - a.example login")
check("7 SCC park still: SCC client id, snapshot written, no backup, allowlist tenant SCC", ver_posts(fp7)[0][2][0]["client_id"] == SCC and fp7.snaps == [SCC] and r7["portal_written"] is True and "backup" not in r7 and r7["allowlist"]["added"] and not r7["errors"], r7["errors"])

# 8 MUTATION: with the lock removed the cross-tenant writes DO happen, so tests 5/5b/6 are real (they fail on the mutant)
real_lock = T._tenant_lock
T._tenant_lock = lambda client, row_id, path: T.tenant_of(client)
try:
    sp8, srid8, sdir8 = scc_queue(); fp8 = FP(sdir8)
    try: T.record_transition("NM", srid8, "needs-human", None, "n", queue_path=sp8, today=DAY, portal=fp8, verify_type="sms", observation=YO.obs("sms", DAY), allowlist_path=LOCAL, vault_item="x"); wrote_scc_row = True
    except Exception as ex: wrote_scc_row = False
    pn8 = nm_queue(); fp8b = FP("mapquest.com")
    try: T.record_transition("SCC", "nm-fix-mapquest", "needs-human", None, "n", queue_path=pn8, today=DAY, portal=fp8b, verify_type="sms", observation=YO.obs("sms", DAY), allowlist_path=LOCAL, vault_item="x"); wrote_nm_row = json.load(open(pn8))["fix_queue"][0]["history"][-1].get("verify_type") == "sms"
    except Exception as ex: wrote_nm_row = False
finally: T._tenant_lock = real_lock
check("8 mutation (lock removed): NM park reaches an SCC row (test 5 would FAIL)", wrote_scc_row is True)
check("8b mutation (lock removed): SCC park reaches an nm- row (test 6 would FAIL)", wrote_nm_row is True)
check("8c lock restored: both refused again", refused(lambda: T.record_transition("SCC", "nm-fix-mapquest", "needs-human", None, "n", queue_path=nm_queue(), today=DAY, portal=FP(), verify_type="sms", observation=YO.obs("sms", DAY))) is not None)

# 9 --create-row: one row, no hand JSON, refuses an existing Directory, SCC refused, dry run writes nothing
pc = nm_queue(); hc = sha(pc)
rd = T.create_row("NM", "foursquare.com", "fix", queue_path=pc, today=DAY, dry_run=True)
check("9 dry run prints the row and writes nothing", rd["row"]["id"] == "nm-fix-foursquare" and sha(pc) == hc and rd["row"]["state"] == "queued" and rd["row"]["mike_approval"] is None, rd["row"])
rc = T.create_row("NM", "ezlocal.com", "create", queue_path=pc, today=DAY)
q9 = json.load(open(pc)); ids = [x["id"] for x in q9["fix_queue"]]
check("9b create writes exactly one queued row, backup made, others untouched", ids == ["nm-fix-mapquest", "nm-fix-bbb", "nm-create-ezlocal"] and q9["fix_queue"][2]["directory"] == "ezlocal.com" and q9["fix_queue"][2]["kind"] == "create" and os.path.exists(pc + ".bak-nm-" + DAY), ids)
check("9c a Directory that already has a row is refused (no second row)", "already has a queue row" in (refused(lambda: T.create_row("NM", "ezlocal.com", "create", queue_path=pc, today=DAY)) or "") and "already has" in (refused(lambda: T.create_row("NM", "mapquest.com", "fix", queue_path=pc, today=DAY)) or "") and len(json.load(open(pc))["fix_queue"]) == 3)
check("9d SCC refused; bad domain and kind refused; wrong queue file refused",
      "not available" in (refused(lambda: T.create_row("SCC", "x.com", "create", queue_path=pc)) or "") and refused(lambda: T.create_row("NM", "not a domain", "create", queue_path=pc)) and refused(lambda: T.create_row("NM", "x.com", "bogus", queue_path=pc))
      and "tenant lock" in (refused(lambda: T.create_row("NM", "x.com", "create", queue_path=scc_queue()[0])) or ""))
# 9e the new row can then be parked in the same session (the "no queue row yet" flow)
fpd = FP("ezlocal.com"); rr = T.record_transition("NM", "nm-create-ezlocal", "needs-human", None, "n", queue_path=pc, today=DAY, portal=fpd, verify_type="sms", observation=YO.obs("sms", DAY), allowlist_path=LOCAL, vault_item="NM - ezlocal.com login")
check("9e a created row parks on the NM tenant: queued -> needs-human with the Your turn row", rr["verification_written"] and ver_posts(fpd)[0][2][0]["client_id"] == NM and not rr["errors"], rr["errors"])

# 10 CLI: --create-row dry run, and the REFUSED line for an SCC client
buf, err = io.StringIO(), io.StringIO(); pcli = nm_queue()
with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
    rc1 = T.main(["--client", "NM", "--create-row", "--domain", "bark.com", "--kind", "create", "--queue", pcli, "--dry-run", "--today", DAY])
    rc2 = T.main(["--client", "SCC", "--create-row", "--domain", "bark.com", "--kind", "create", "--queue", pcli])
check("10 CLI create-row dry run prints the row (exit 0); SCC REFUSED (exit 1)", rc1 == 0 and "nm-create-bark" in buf.getvalue() and rc2 == 1 and "REFUSED" in err.getvalue())

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
