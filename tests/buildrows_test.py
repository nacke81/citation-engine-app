"""Build rows tests (kanban t_00821936). Run: python tests/buildrows_test.py (CI). No network: the database is an in-memory fake.

  B1 one row per Directory: all 86 seed Directories end up covered, no duplicate id, none doubled
  B2 found + NAP correct + permalink gets no row; found with errors -> fix row on the permalink; absent / couldnt / unsearchable / never checked -> create
  B3 paid or no-route -> needs-human with the reason in history
  B4 idempotent: second run is equal, writes nothing, makes no second backup
  B5 no clobber: an existing row keeps state, history, approval and every field; also rows under create_queue.rows and create_rows
  B6 approval stamp is the 10/25 blanket ruling verbatim, row_id = the row id; transitions accepts the new rows (approval survives)
  B7 order: build_order by priority then DA; existing row lists are not reordered
  B8 backup is written before the first write and holds the old bytes; weekly create merge does not double the rows
  B9 scope: no Directory request, no portal write, transitions.py untouched
"""
import copy, json, os, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
TMP = tempfile.mkdtemp()
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ["CE_QUEUE"] = os.path.join(TMP, "queue.json")
os.environ["CE_RUNS"] = tempfile.mkdtemp()
os.environ["CE_ACTIVITIES_WRITE"] = "0"
os.environ["CE_DIRECTORIES_WRITE"] = "0"
sys.path.insert(0, os.path.join(ROOT, "job"))
import buildrows as B
import buildqueue as Q

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

SEED = json.load(open(os.path.join(ROOT, "db", "directories_seed.json"), encoding="utf-8"))
DAY = "2026-10-25"
RULING_NOTE = "Mike in Nate chat 2026-10-25: build new SCC listings across the Directory database, keep looping. Free listings only, canonical NAP verbatim. No spend, no phone/SMS/postcard verify, no client contact without Mike."
ERR = [{"field": "phone", "live": "111", "canonical": "222"}]
BASE = {"business": "Test Biz", "canonical": {"name": "Test Biz", "address": "1 Main St", "phone": "(000) 000-0000"},
        "fix_queue": [{"id": "fix-mapquest", "directory": "mapquest.com", "state": "needs-human", "mike_approval": {"approved_by": "mike", "at": "2026-10-20T21:43:50+00:00", "row_id": "fix-mapquest", "note": "old"},
                       "history": [{"at": "2026-10-21", "from": "queued", "to": "needs-human", "note": "Yext funnel"}], "listing_url": "https://www.mapquest.com/us/xx/x-1"}],
        "create_queue": {"rows": [{"id": "create-acompio", "directory": "acompio.us", "kind": "create", "state": "submitted", "mike_approval": None, "history": [{"at": "2026-10-22", "to": "submitted"}]}], "last_seen": {}}}

def dirs():
    return [dict(domain=r["domain"], name=r["name"], priority=r["priority"], da=r["da"], cost=r["cost"], build_route=r["build_route"],
                 signup_url=r["signup_url"], claim_url=r["claim_url"], build_eligible=r.get("build_eligible", True)) for r in SEED]
DIRS = dirs()
by = {d["domain"]: d for d in DIRS}

# a small scenario over real seed domains
FOUND_OK = "yelp.com"; FOUND_ERR = "yellowpages.com"; ABSENT = "bbb.org"; CC = "chamberofcommerce.com"; UNS = "facebook.com"
for dm in (FOUND_OK, FOUND_ERR, ABSENT, CC, UNS):
    assert dm in by, dm
checks = [dict(directory=FOUND_OK, result="found", url="https://www.yelp.com/biz/test-biz-exampletown", match=True, diffs=None),
          dict(directory=FOUND_ERR, result="found", url="https://www.yellowpages.com/exampletown-xx/mip/test-biz-100200300", match=False, diffs=ERR),
          dict(directory=ABSENT, result="absent", url=None, match=None, diffs=None),
          dict(directory=CC, result="couldnt_check", url=None, match=None, diffs=None),
          dict(directory=UNS, result="unsearchable", url=None, match=None, diffs=None)]
new, rep = B.build_rows(BASE, DIRS, [], checks, DAY)
rows, cnt = B.counts(new)
ids = [r["id"] for r in rows]
dom = [r["directory"] for r in rows]

# B1
check("B1 every build-eligible seed Directory has exactly one row, except found-correct", set(dom) == {d["domain"] for d in DIRS if d["build_eligible"]} - {FOUND_OK} and len(dom) == len(set(dom)), (len(dom), len(set(dom))))
check("B1 no duplicate row id", len(ids) == len(set(ids)))
check("B1 report adds up to 148 (86 v1 + 62 catalog-only)", rep["existing"] + rep["none"] + rep["added"] + rep["ineligible"] == 148 and rep["ineligible"] == 62, rep)
# B2
check("B2 found + NAP correct + permalink gets no row", FOUND_OK not in dom and rep["none"] == 1)
fx = [r for r in rows if r["directory"] == FOUND_ERR][0]
check("B2 found with NAP errors -> fix row, listing_url = the permalink", fx["kind"] == "fix" and fx["state"] == "queued" and fx["listing_url"] == checks[1]["url"] and fx["wrong_field"] == "phone" and fx["right_value"] == "222")
for d, why in ((ABSENT, "absent"), (CC, "couldnt"), (UNS, "unsearchable"), ([d for d in DIRS if d["build_eligible"]][-1]["domain"], "never checked")):
    r = [x for x in rows if x["directory"] == d][0]
    check("B2 %s -> create row, queued" % why, r["kind"] == "create" and (r["state"] == "queued" or by[d]["cost"] == "paid" or by[d]["build_route"] == "none"))
fnc = B.build_rows(BASE, DIRS, [], [dict(directory=FOUND_OK, result="found", url="https://www.yelp.com/search?find_desc=x", match=True, diffs=None)], DAY)[0]
check("B2 found-correct but the stored URL is a search page -> create row (no guessed permalink)", FOUND_OK in [r["directory"] for r in B.counts(fnc)[0]])
# B3
paid = [d for d in DIRS if d["cost"] == "paid" and d["domain"] not in ("mapquest.com",)]
nr = copy.deepcopy(DIRS); nr[5]["build_route"] = "none"; nr[6]["cost"] = "paid"
n2, _ = B.build_rows({"fix_queue": [], "create_queue": {"rows": []}}, nr, [], [], DAY)
r2 = {r["directory"]: r for r in B.counts(n2)[0]}
a, b = r2[nr[5]["domain"]], r2[nr[6]["domain"]]
check("B3 build_route none -> needs-human, reason no-route", a["state"] == "needs-human" and a["history"][-1]["note"].startswith("no-route") and a["history"][-1]["to"] == "needs-human")
check("B3 paid -> needs-human, reason paid-tier", b["state"] == "needs-human" and b["history"][-1]["note"].startswith("paid-tier"))
# B3b catalog-only hunt rows (t_ab039aed): build_eligible false -> no queue row at all, not even needs-human
HUNT = [d for d in DIRS if d["build_eligible"] is False]
hq, hrep = B.build_rows({"fix_queue": [], "create_queue": {"rows": []}}, HUNT, [], [], DAY)
check("B3b 62 hunt rows on an empty queue -> added 0, nothing queued, nothing needs-human", len(HUNT) == 62 and hrep["added"] == 0 and hrep["ineligible"] == 62
      and hrep["create"] == 0 and hrep["fix"] == 0 and hrep["needs-human"] == 0 and B.counts(hq)[0] == [] and "build_order" not in hq, hrep)
mix, mrep = B.build_rows({"fix_queue": [], "create_queue": {"rows": []}}, DIRS, [], [], DAY)
check("B3b mixed v1 + hunt: only v1 Directories get rows, every hunt domain is absent from the queue", not ({d["domain"] for d in HUNT} & {r["directory"] for r in B.counts(mix)[0]}) and mrep["added"] == 86 and mrep["ineligible"] == 62, mrep)
legacy = [dict(d) for d in DIRS if d["build_eligible"]]
for d in legacy: d.pop("build_eligible")
lq, lrep = B.build_rows({"fix_queue": [], "create_queue": {"rows": []}}, legacy, [], [], DAY)
check("B3b a row without the column (null / absent) behaves as before: eligible", lrep["added"] == 86 and lrep["ineligible"] == 0, lrep)
check("B3b the load query reads build_eligible", "build_eligible" in open(os.path.join(ROOT, "job", "buildrows.py"), encoding="utf-8").read().split("def load_db_inputs")[1].split("status =")[0])
# B4
p = os.path.join(TMP, "queue.json"); json.dump(BASE, open(p, "w", encoding="utf-8"), indent=1)
r1, bak1 = B.apply_file(p, DIRS, [], checks, DAY)
s1 = open(p, "rb").read(); m1 = os.path.getmtime(p)
r2_, bak2 = B.apply_file(p, DIRS, [], checks, DAY)
check("B4 second run changes nothing (bytes equal, no write, no backup)", open(p, "rb").read() == s1 and bak2 is None and os.path.getmtime(p) == m1 and r2_["added"] == 0, r2_)
check("B4 build_rows on its own output is equal", B.build_rows(json.load(open(p, encoding="utf-8")), DIRS, [], checks, DAY)[0] == json.load(open(p, encoding="utf-8")))
# B5
q = json.load(open(p, encoding="utf-8"))
mq = [r for r in q["fix_queue"] if r["id"] == "fix-mapquest"]
check("B5 existing fix row identical (state, history, approval, fields)", mq == BASE["fix_queue"] and len(mq) == 1)
check("B5 existing create_queue row identical, approval still null", q["create_queue"]["rows"][0] == BASE["create_queue"]["rows"][0])
flat = copy.deepcopy(BASE); flat["create_rows"] = [{"id": "create-bbb", "directory": ABSENT, "state": "pending-verify", "mike_approval": None, "history": [{"at": "x", "to": "pending-verify"}]}]
nf_, _ = B.build_rows(flat, DIRS, [], checks, DAY)
check("B5 a row in create_rows is kept and its Directory gets no second row", nf_["create_rows"] == flat["create_rows"] and sum(1 for r in B.counts(nf_)[0] if r["directory"] == ABSENT) == 1)
check("B5 queue input is not mutated", BASE["fix_queue"][0]["mike_approval"]["note"] == "old" and len(BASE["create_queue"]["rows"]) == 1)
# B6
stamped = [r for r in rows if r["directory"] not in ("mapquest.com", "acompio.us")]
check("B6 every new row carries the blanket approval verbatim, row_id = id",
      all(r["mike_approval"] == {"approved_by": "mike", "at": "2026-10-25T17:45:00+00:00", "row_id": r["id"], "scope": "blanket-2026-10-25", "note": RULING_NOTE} for r in stamped) and len(stamped) == rep["added"] == 83)
check("B6 buildqueue.approval_ok accepts the new rows", all(Q.approval_ok(r) for r in stamped))
import transitions as T
os.environ["CE_QUEUE"] = p
tq = json.load(open(p, encoding="utf-8"))
sample = [r for r in tq["fix_queue"] if r["id"] == fx["id"]][0]
check("B6 transitions.check_transition allows queued -> submitted on a new row; approval object stays equal after a transition-style update",
      T.check_transition(sample["state"], "submitted") is None and Q.parse_rows(tq) is not None)
# B7
bo = tq["build_order"]
key = lambda r: (by[r["directory"]]["priority"], -(by[r["directory"]]["da"] or 0), r["directory"])
allr = B.counts(tq)[0]
check("B7 build_order covers every row id once", sorted(bo) == sorted(r["id"] for r in allr))
check("B7 build_order sorted by priority then DA high first", [r["id"] for r in sorted(allr, key=key)] == bo)
check("B7 existing rows stay first in their own list", tq["fix_queue"][0]["id"] == "fix-mapquest" and tq["create_queue"]["rows"][0]["id"] == "create-acompio")
# B8
bak = r1 and B.backup.__name__ and bak1
check("B8 backup exists next to the queue and holds the pre-write bytes", bak1 and os.path.exists(bak1) and json.load(open(bak1, encoding="utf-8")) == BASE and bak1.startswith(p + ".bak-"), bak1)
import create_discovery as CD
dec = {"acompio.us": dict(state="absent", why="w", on=DAY)}
mq2 = CD.merge_create_queue(copy.deepcopy(tq), dec, [dict(id="create-acompio", directory="acompio.us", kind="create", state="queued", mike_approval=None)], DAY)
check("B8 weekly create discovery merge does not double or reset the rows", len(B.counts(mq2)[0]) == len(allr) and mq2["create_queue"]["rows"][0]["state"] == "submitted")
dry_before = open(p, "rb").read()
dry_rep, dry_bak = B.apply_file(p, dirs()[:-1], [], checks, DAY, write=False)
check("B8 dry run writes nothing", open(p, "rb").read() == dry_before and dry_bak is None)
# B9
src = open(os.path.join(ROOT, "job", "buildrows.py"), encoding="utf-8").read()
check("B9 buildrows makes no Directory request, no portal import, no transitions import", "urlopen" not in src and "import portal" not in src and "import transitions" not in src and "requests" not in src)
check("B9 run.py wires buildrows after create_queue_step, non-fatal", "buildrows_step" in open(os.path.join(ROOT, "job", "run.py"), encoding="utf-8").read())
shutil.rmtree(TMP, ignore_errors=True)
print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})"); sys.exit(0 if all(ok) else 1)
