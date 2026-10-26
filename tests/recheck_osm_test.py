"""OSM reader + Chrome-route (manta) + Proof for rows already live (t_1c503c7f). No network, no browser: urlopen and the Chrome fetcher are fakes."""
import os, sys, copy, json, io, tempfile, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ.pop("CE_ACTIVITIES_WRITE", None)
os.environ["CE_RUNS"] = tempfile.mkdtemp(prefix="ce-runs-")
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import transitions as T
import recheck as R

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

CANON = {"name": "Alder Care Consulting & Solutions", "address": "100 Example, Exampleton KY 40000", "phone": "(502) 555-0101"}
IDENT = json.load(open(os.path.join(HERE, "test_identity.json"), encoding="utf-8"))
DAY = "2026-11-02"
NODE = "https://www.openstreetmap.org/node/5550001111"
API = "https://api.openstreetmap.org/api/0.6/node/5550001111.json"
TAGS = {"office": "consulting", "name": "Alder Care Consulting & Solutions", "addr:housenumber": "100", "addr:street": "Example", "addr:city": "Exampleton",
        "addr:state": "KY", "addr:postcode": "40000", "phone": "+1 502 555 0101", "website": "https://alder.example"}

class Resp(io.BytesIO):
    status = 200
    def __enter__(s): return s
    def __exit__(s, *a): return False
    def geturl(s): return NODE
SEEN = []
def fake_open(tags=TAGS, visible=True, code=None):
    def f(req, timeout=0):
        SEEN.append((req.full_url, req.get_method(), dict(req.header_items())))
        if code: raise urllib.error.HTTPError(req.full_url, code, "x", {}, None)
        el = {"type": "node", "id": 5550001111, "lat": 37.3, "lon": -87.4, "tags": tags}
        if not visible: el["visible"] = False
        return Resp(json.dumps({"elements": [el]}).encode())
    return f

# O1 reader
urllib.request.urlopen = fake_open()
pg = R.osm_fetch(NODE)
check("O1 reads the API json URL with one GET", SEEN[-1][0] == API and SEEN[-1][1] == "GET", str(SEEN[-1][:2]))
check("O1 no auth header sent (public read)", not any(k.lower() == "authorization" for k in SEEN[-1][2]))
check("O1 tags rendered as listing lines", pg.status == 200 and pg.text.split("\n")[:3] == ["Alder Care Consulting & Solutions", "100 Example", "Exampleton, KY 40000"], pg.text)
c = R.compare(pg.text, CANON, None)
check("O2 compare: exact NAP tags match", c["verdict"] == "match", str(c))

urllib.request.urlopen = fake_open(dict(TAGS, phone="+1 502 555 0199"))
c = R.compare(R.osm_fetch(NODE).text, CANON, None)
check("O3 wrong phone tag is a mismatch", c["verdict"] == "mismatch" and c["wrong"][0][0] == "phone", str(c))
urllib.request.urlopen = fake_open(dict(TAGS, **{"addr:street": "Elsewhere"}))
c = R.compare(R.osm_fetch(NODE).text, CANON, None)
check("O4 wrong street tag is a mismatch", c["verdict"] == "mismatch", str(c))
urllib.request.urlopen = fake_open(dict(TAGS, name="Alder Care Consltng Solutions"))
c = R.compare(R.osm_fetch(NODE).text, CANON, None)
check("O5 typo in name tag is a mismatch, not a match", c["verdict"] != "match", str(c))

urllib.request.urlopen = fake_open(visible=False)
pg = R.osm_fetch(NODE)
check("O6 deleted node -> not readable", pg.status == 404 and R.compare(pg.text, CANON)["verdict"] == "unreadable")
urllib.request.urlopen = fake_open(code=410)
pg = R.osm_fetch(NODE)
check("O7 HTTP 410 -> Page with status, never raises", pg.status == 410 and pg.err == "HTTP 410")
check("O8 non-node URL refused, no request", R.osm_fetch("https://www.openstreetmap.org/way/5").status == 0 and R.osm_node_id("https://evil.example/https://www.openstreetmap.org/node/1") is None)
check("O9 node id regex: only digits", R.osm_node_id("https://www.openstreetmap.org/node/123/") == "123" and R.osm_node_id("https://www.openstreetmap.org/node/12a") is None)

# get_page routes OSM nodes to the API reader and never to plain/Chrome
urllib.request.urlopen = fake_open()
def boom(u): raise AssertionError("plain/chrome used for an OSM node")
page, how = R.get_page(NODE, boom, boom, CANON)
check("O10 get_page -> osm route, no plain/Chrome", how == "osm" and page.status == 200)

# recheck on a LIVE row: stable reads + Proof-only
class FakeDB:
    owner = "owner-1"
    def __init__(s): s.calls = []
    def call(s, method, path, body=None, prefer=None): s.calls.append((method, path, body))
class FakePortal:
    def __init__(s): s.calls = []; s.snap = {"found": 1, "directories": []}
    def latest_snapshot(s, cid): return {"payload": copy.deepcopy(s.snap)}
    def upsert_snapshot(s, cid, day, payload): s.calls.append(("snap", day))
    def call(s, method, path, body=None, prefer=None): s.calls.append((method, path, body))

def mkrow(rid, d, url, state="live"):
    return {"id": rid, "directory": d, "state": state, "mike_approval": None, "evidence_url": url, "listing_url": url, "history": []}
def queue(rows):
    p = os.path.join(tempfile.mkdtemp(), "q.json"); json.dump({"canonical": CANON, "fix_queue": [], "create_rows": rows}, open(p, "w")); return p
def run(rows, chrome=None, **kw):
    p = queue(rows); db, fp = FakeDB(), FakePortal()
    rec = lambda *a, **k: T.record_transition(*a, portal=fp, activities=fp, verification=fp, directories=db, **k)
    plain = lambda u: R.Page(403, u, "", err="HTTP 403")
    res = R.recheck(json.load(open(p)), IDENT, plain=plain, chrome=chrome, record=rec, db=db, queue_path=p, today=DAY, **kw)
    return res, json.load(open(p)), db

reads = []
urllib.request.urlopen = lambda req, timeout=0: (reads.append(req.full_url), fake_open()(req))[1]
res, q, db = run([mkrow("create-openstreetmap", "openstreetmap.org", NODE)], write=True, include_live=True, only={"create-openstreetmap"}, proof_live=True)
proofs = [c for c in db.calls if "ce_directory_status" in c[1] and c[2][0].get("proof_nap_match") is True]
check("L1 OSM live row: 3 stable API reads", len(reads) == R.STABLE_READS, str(len(reads)))
check("L1 Proof written once, url = node page, nap quoted", len(proofs) == 1 and proofs[0][2][0]["proof_url"] == NODE and "Alder Care" in proofs[0][2][0]["proof_nap"], str(proofs))
check("L1 build_action new (create row), state stays live, no transition", proofs[0][2][0]["build_action"] == "new" and res[0]["after"] == "live" and q["create_rows"][0]["state"] == "live" and q["create_rows"][0]["history"] == [])

res, q, db = run([mkrow("create-openstreetmap", "openstreetmap.org", NODE)], write=True, include_live=True, only={"create-openstreetmap"})
check("L2 without --proof-live nothing is written for a live row", not [c for c in db.calls if "ce_directory_status" in c[1]])
res, q, db = run([mkrow("create-openstreetmap", "openstreetmap.org", NODE)], write=True, include_live=True, proof_live=True)
check("L3 --proof-live without --row writes nothing (never a sweep)", not [c for c in db.calls if "ce_directory_status" in c[1]])
res, q, db = run([mkrow("create-openstreetmap", "openstreetmap.org", NODE), mkrow("create-other", "other.example", "https://other.example/biz/1")],
                 chrome=lambda u: R.Page(200, u, "Home\nAlder Care Consulting & Solutions\n100 Example\nExampleton, KY 40000\n(502) 555-0101\n" + "Lorem ipsum dolor sit amet. " * 12),
                 write=True, include_live=True, only={"create-openstreetmap"}, proof_live=True)
check("L4 only the named row gets Proof", len(res) == 1 and {c[2][0]["directory"] for c in db.calls if "ce_directory_status" in c[1]} == {"openstreetmap.org"}, str(res))

# flip on read 2 -> no Proof
state = {"n": 0}
def flip(req, timeout=0):
    state["n"] += 1
    return fake_open(TAGS if state["n"] != 2 else dict(TAGS, phone="+1 502 555 0199"))(req)
urllib.request.urlopen = flip
res, q, db = run([mkrow("create-openstreetmap", "openstreetmap.org", NODE)], write=True, include_live=True, only={"create-openstreetmap"}, proof_live=True)
check("L5 unstable OSM read (phone flips on read 2): no Proof", not [c for c in db.calls if "ce_directory_status" in c[1]] and res[0]["verdict"] == "mismatch", str(res[0]["verdict"]))

# manta: plain 403 -> Chrome route (signed-out), 3 stable chrome reads, Proof
MANTA = "https://www.manta.com/c/m0example/alder-care-consulting-solutions"
mtxt = "Alder Care Consulting & Solutions\n100 Example\nExampleton, KY 40000\n(502) 555-0101\n" + "Claimed. Lorem ipsum dolor sit amet. " * 8
calls = []
def chrome(u): calls.append(u); return R.Page(200, u, mtxt, html="<html>%s</html>" % mtxt)
urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network"))
res, q, db = run([mkrow("create-manta", "manta.com", MANTA)], chrome=chrome, write=True, include_live=True, only={"create-manta"}, proof_live=True)
proofs = [c for c in db.calls if "ce_directory_status" in c[1] and c[2][0].get("proof_nap_match") is True]
check("M1 manta: plain 403 -> Chrome, 3 stable reads", res[0]["via"] == "chrome" and len(calls) >= R.STABLE_READS, str((res[0].get("via"), len(calls))))
check("M1 manta Proof written with the permalink", len(proofs) == 1 and proofs[0][2][0]["proof_url"] == MANTA and proofs[0][2][0]["directory"] == "manta.com")
calls.clear()
res, q, db = run([mkrow("create-manta", "manta.com", MANTA)], chrome=lambda u: R.Page(403, u, "Just a moment..."), write=True, include_live=True, only={"create-manta"}, proof_live=True)
check("M2 manta walled in Chrome -> no Proof", not [c for c in db.calls if "ce_directory_status" in c[1]])

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
