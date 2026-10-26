"""fill_signup_urls tests (t_64c4d511). Run: python tests/fill_signup_urls_test.py (CI). Temp queue only, no network."""
import os, sys, json, copy, tempfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
TMP = tempfile.mkdtemp(); os.environ["CE_QUEUE"] = os.path.join(TMP, "q.json")
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import signup_urls as S
import fill_signup_urls as F
ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)
def row(i, d, state, **kw): return dict(id=i, directory=d, state=state, history=[{"at": "2026-10-25", "from": "queued", "to": state, "note": "n"}], mike_approval={"by": "Mike", "row_id": i}, signup_url=None, claim_url=None, **kw)

CD = {"cortera.com": "https://www.cortera.com/", "bad.example": "http://insecure.example/", "cred.example": "https://u:pw@cred.example/x"}
q = {"fix_queue": [row("fix-merchantcircle", "merchantcircle.com", "needs-human", kind="fix", listing_url="https://www.merchantcircle.com/test-biz-exampleville-zz"),
                   row("fix-hotfrog", "hotfrog.com", "live", kind="fix", listing_url="https://www.hotfrog.com/company/x")],
     "create_queue": {"rows": [row("create-bbb", "bbb.org", "submitted", kind="create"), row("create-yelp", "yelp.com", "needs-human", kind="create"),
                               row("create-ezlocal", "ezlocal.com", "needs-human", kind="create"), row("create-brownbook", "brownbook.net", "found", kind="create"),
                               row("create-bizapedia", "bizapedia.com", "live", kind="create"), row("create-cortera", "cortera.com", "queued", kind="create"),
                               row("create-bad", "bad.example", "queued", kind="create"), row("create-cred", "cred.example", "queued", kind="create"),
                               row("create-nothing", "nothing.example", "queued", kind="create")]}}
before = copy.deepcopy(q)
done = F.fill(q, CD)
def find(qq, i): return next(r for r in S._rows(qq) if r["id"] == i)
check("F1 playbook URLs set: bbb, yelp, ezlocal, brownbook, bizapedia", all(find(q, i)["signup_url"] for i in ("create-bbb", "create-yelp", "create-ezlocal", "create-brownbook", "create-bizapedia")))
check("F1 BBB /get-listed/form, EZlocal /free-business-listing/, Brownbook /add-business", find(q, "create-bbb")["signup_url"] == "https://www.bbb.org/get-listed/form" and find(q, "create-ezlocal")["signup_url"] == "https://ezlocal.com/free-business-listing/" and find(q, "create-brownbook")["signup_url"] == "https://www.brownbook.net/add-business")
check("F2 MerchantCircle claim_url built from the row's slug", find(q, "fix-merchantcircle")["claim_url"] == "https://www.merchantcircle.com/signup?business=test-biz-exampleville-zz&claiming=True")
check("F3 CREATE_DIRS / db URL fills a row with no playbook", find(q, "create-cortera")["signup_url"] == "https://www.cortera.com/")
check("F4 http:// and credential URLs refused", find(q, "create-bad")["signup_url"] is None and find(q, "create-cred")["signup_url"] is None)
check("F5 unknown directory untouched; fix row on a live listing gets no signup_url", find(q, "create-nothing") == find(before, "create-nothing") and find(q, "fix-hotfrog") == find(before, "fix-hotfrog"))
changed = {r["id"]: {k for k in r if r[k] != find(before, r["id"]).get(k)} for r in S._rows(q)}
check("F6 only signup_url / claim_url changed; state, history, approval untouched", all(v <= {"signup_url", "claim_url"} for v in changed.values()), str(changed))
q2 = copy.deepcopy(before); find(q2, "create-bbb")["signup_url"] = "https://hand.example/x"; F.fill(q2, CD)
check("F7 a hand-set URL is never overwritten", find(q2, "create-bbb")["signup_url"] == "https://hand.example/x")
q3 = copy.deepcopy(q)
check("F8 idempotent: second fill sets nothing", F.fill(q3, CD) == [] and q3 == q)

class FakeDB:
    def __init__(self): self.calls = []
    def call(self, m, path, body=None, prefer=None):
        self.calls.append((m, path)); return [{"domain": "db.example", "signup_url": "https://db.example/join"}, {"domain": "botw.org", "signup_url": "https://db.example/override"}]
db = FakeDB(); m = F._create_dirs(db)
check("F9 db read is GET only; db fills where CREATE_DIRS has none and never overrides it", db.calls and all(c[0] == "GET" for c in db.calls) and m.get("db.example") == "https://db.example/join" and m["botw.org"] == "https://botw.org/")

# CLI on a file: dry run, real run, backup, idempotent
json.dump(before, open(os.environ["CE_QUEUE"], "w"))
check("F10 dry run writes nothing", F.main(["--dry-run"]) == 0 and json.load(open(os.environ["CE_QUEUE"])) == before)
check("F10 real run exits 0", F.main([]) == 0)
after = json.load(open(os.environ["CE_QUEUE"]))
bak = [f for f in os.listdir(TMP) if ".bak-" in f]
check("F10 backup made and equals the original", len(bak) == 1 and json.load(open(os.path.join(TMP, bak[0]))) == before)
check("F10 file has the playbook URLs", find(after, "create-bbb")["signup_url"] == "https://www.bbb.org/get-listed/form")
check("F10 second run: no second backup, file unchanged", F.main([]) == 0 and json.load(open(os.environ["CE_QUEUE"])) == after and len([f for f in os.listdir(TMP) if ".bak-" in f]) == 1)
src = open(os.path.join(HERE, "..", "job", "fill_signup_urls.py"), encoding="utf-8").read()
check("F11 no browser or Directory fetch; db import only behind --from-db", not any(w in src for w in ("urlopen", "urllib.request", "requests", "socket", "subprocess", "playwright", "import portal", "import transitions")))
shutil.rmtree(TMP, ignore_errors=True)
print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})"); sys.exit(0 if all(ok) else 1)
