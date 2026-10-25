"""signup_urls tests. Run: python tests/signup_urls_test.py (CI). Temp queue only, no network."""
import os, sys, json, copy, tempfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
TMP = tempfile.mkdtemp(); os.environ["CE_QUEUE"] = os.path.join(TMP, "q.json")
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import signup_urls as S
ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)
def row(i, d, state, **kw): return dict(id=i, directory=d, state=state, history=[{"at": "2026-10-25", "from": "queued", "to": state, "note": "n"}], mike_approval={"by": "Mike", "row_id": i}, signup_url=None, claim_url=None, **kw)
q = {"fix_queue": [row("fix-merchantcircle", "merchantcircle.com", "needs-human"), row("fix-other", "other.com", "queued")],
     "create_queue": {"rows": [row("create-bbb", "bbb.org", "needs-human"), row("create-ezlocal", "ezlocal.com", "needs-human"), row("create-brownbook", "brownbook.net", "needs-human"), row("create-yelp", "yelp.com", "needs-human")]}}
json.dump(q, open(os.environ["CE_QUEUE"], "w"))
before = copy.deepcopy(q)
check("U1 dry run writes nothing", S.main(["--dry-run"]) == 0 and json.load(open(os.environ["CE_QUEUE"])) == before)
check("U2 real run exits 0", S.main([]) == 0)
after = json.load(open(os.environ["CE_QUEUE"]))
def find(qq, i): return next(r for r in S._rows(qq) if r["id"] == i)
check("U3 BBB signup_url", find(after, "create-bbb")["signup_url"] == "https://www.bbb.org/get-listed/form")
check("U4 MerchantCircle claim_url has claiming=True", find(after, "fix-merchantcircle")["claim_url"].endswith("/signup?business=senior-care-consulting-solutions-madisonville-ky&claiming=True"))
check("U5 EZlocal and Brownbook", find(after, "create-ezlocal")["signup_url"] == "https://ezlocal.com/free-business-listing/" and find(after, "create-brownbook")["signup_url"] == "https://www.brownbook.net/add-business")
changed = {r["id"]: {k for k in r if r[k] != find(before, r["id"]).get(k)} for r in S._rows(after)}
check("U6 only signup_url/claim_url changed; state, history, approval untouched", all(v <= {"signup_url", "claim_url"} for v in changed.values()), str(changed))
check("U7 rows with no playbook URL untouched", find(after, "create-yelp") == find(before, "create-yelp") and find(after, "fix-other") == find(before, "fix-other"))
bak = [f for f in os.listdir(TMP) if ".bak-" in f]
check("U8 backup made and equals the original", len(bak) == 1 and json.load(open(os.path.join(TMP, bak[0]))) == before)
check("U9 idempotent: second run writes nothing, no second backup", S.main([]) == 0 and json.load(open(os.environ["CE_QUEUE"])) == after and len([f for f in os.listdir(TMP) if ".bak-" in f]) == 1)
q2 = copy.deepcopy(before); find(q2, "create-bbb")["signup_url"] = "https://hand.example/x"; S.fill(q2)
check("U10 a hand-set URL is never overwritten", find(q2, "create-bbb")["signup_url"] == "https://hand.example/x")
src = open(os.path.join(HERE, "..", "job", "signup_urls.py"), encoding="utf-8").read()
check("U11 no network, browser or portal code", not any(w in src for w in ("urllib", "requests", "socket", "subprocess", "import portal", "import transitions", "playwright")))
shutil.rmtree(TMP, ignore_errors=True)
print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})"); sys.exit(0 if all(ok) else 1)
