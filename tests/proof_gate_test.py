"""Proof gate tests (t_5871cdf9): proof_step may move a row live only when recheck's comparator says `match` on the proof_url page. Run: python tests/proof_gate_test.py. No network."""
import os, sys, json, tempfile, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ.pop("CE_ACTIVITIES_WRITE", None)
os.environ["CE_RUNS"] = tempfile.mkdtemp(prefix="ce-runs-")
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import transitions as T
import proof as PR
import recheck as R

def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

TMP = tempfile.mkdtemp()
DAY = "2026-11-03"
URL = "https://a.example/listing/1"
CANON = {"name": "Alder Care Consulting & Solutions", "address": "100 Example, Exampleton KY 40000", "phone": "(502) 555-0101"}
PAD = " Lorem ipsum dolor sit amet." * 12
PARTIAL = "Home\nAlder Care Consulting & Solutions\nAlder Care Consulting & Solutions\n100 Example\n(502) 555-0101\n" + PAD   # the nextdoor shape: no city/state/zip
FULL = "Home\nAlder Care Consulting & Solutions\n100 Example\nExampleton, KY 40000\n(502) 555-0101\n" + PAD
SHELL = "<html><script>app()</script></html>"

class FakeDB:
    owner = "o"
    def __init__(self): self.calls = []
    def call(self, method, path, body=None, prefer=None): self.calls.append((method, path, body))
class FakePortal:
    def __init__(self): self.calls = []
    def latest_snapshot(self, cid): return {"payload": {"found": 1, "directories": []}}
    def upsert_snapshot(self, cid, day, payload): self.calls.append(("snap", day))
    def call(self, method, path, body=None, prefer=None): self.calls.append((method, path, body))

def reader_for(text):
    return lambda url, canon: R.compare(text, canon)

def queue():
    p = os.path.join(TMP, "q%d.json" % len(os.listdir(TMP)))
    row = {"id": "create-a", "directory": "a.example", "state": "needs-human", "mike_approval": None, "evidence_url": None, "history": []}
    json.dump({"canonical": CANON, "create_rows": [row]}, open(p, "w")); return p

def chk():   # the LOOSE check proof.verdict() accepts today: name, street, phone matched
    return dict(biz="SCC", directory="a.example", result="found", url=URL, nap_shown="Alder Care Consulting & Solutions | 100 Example | (502) 555-0101",
                name_match=True, street_match=True, phone_match=True, match=True, diffs=[], note=None)

def run(text, reader=None):
    p = queue(); db, fp = FakeDB(), FakePortal()
    def record(*a, **k): return T.record_transition(*a, portal=fp, activities=fp, verification=fp, directories=db, **k)
    before = open(p, "rb").read()
    res = PR.proof_step([chk()], DAY, queue_path=p, db=db, record=record, reader=reader or reader_for(text))
    return res, db, fp, p, before

check("G0 the loose verdict still says match on the partial check (the old bug's input)", PR.verdict(chk()) == "match")
check("G0 recheck.compare calls the partial page nap-incomplete", R.compare(PARTIAL, CANON)["verdict"] == "nap-incomplete", R.compare(PARTIAL, CANON))

res, db, fp, p, before = run(PARTIAL)
check("G1 partial NAP (name+street+phone, no city/state/zip): nothing moves, nothing written", not res["moved"] and not db.calls and not fp.calls and open(p, "rb").read() == before and res["untouched"] == ["a.example"], res)

res, db, fp, p, before = run(FULL)
q = json.load(open(p))
s = [c[2][0] for c in db.calls if c[0] == "POST" and c[1].startswith("ce_directory_status")]
check("G2 full canonical NAP: row moves live with Proof", len(res["moved"]) == 1 and q["create_rows"][0]["state"] == "live" and s and s[0].get("proof_nap_match") is True and not res["errors"], res)
check("G2 proof_nap is the comparator's NAP (carries the matched street)", "100 Example" in (s[0].get("proof_nap") or ""), s)

for label, text in (("JS shell / unreadable", SHELL), ("wrong city/zip -> mismatch", FULL.replace("40000", "99999")), ("hidden/paused -> not-public", FULL + "\nHIDDEN until ACTIVATED")):
    res, db, fp, p, before = run(text)
    check("G3 %s: nothing written, row not moved" % label, not res["moved"] and not db.calls and not fp.calls and open(p, "rb").read() == before, (R.compare(text, CANON)["verdict"], res))

# PROOF and RECHECK read the same page through the same compare(): they cannot disagree
for label, text in (("partial", PARTIAL), ("full", FULL), ("shell", SHELL), ("wrong zip", FULL.replace("40000", "99999"))):
    res, db, fp, p, before = run(text)
    recheck_says_match = R.compare(text, CANON)["verdict"] == "match"
    check("G4 %s: PROOF moves iff RECHECK says match" % label, bool(res["moved"]) == recheck_says_match)

# a comparator read that raises writes nothing and reports the error
def boom(u, c): raise RuntimeError("chrome down")
res, db, fp, p, before = run(None, reader=boom)
check("G5 comparator read fails: nothing written, error reported", not res["moved"] and not db.calls and open(p, "rb").read() == before and len(res["errors"]) == 1, res)

# the default reader goes through recheck.read_listing (one read path)
src = open(os.path.join(HERE, "..", "job", "proof.py"), encoding="utf-8").read()
check("G6 proof.py uses recheck.read_listing", "RC.read_listing(" in src)

# structured-address reader (t_5871cdf9 round 2): the nextdoor page shape (sanitized to the test identity) (fixture, saved 11/03) carries the address in its own markup, not in the text block
import claim
ND = open(os.path.join(HERE, "fixtures", "nextdoor-scc-20261103.html"), encoding="utf-8").read()
ND_CANON = {"name": CANON["name"], "address": "100 Example, Exampleton, KY 40000", "phone": "(502) 555-0101"}
c = R.compare(claim.html_to_text(ND), ND_CANON, ND)
check("N1 nextdoor page shape (sanitized to the test identity) gives match with full NAP", c["verdict"] == "match" and "Exampleton, KY 40000" in c["nap"], c)
check("N2 same text without the html (no markup) stays nap-incomplete", R.compare(claim.html_to_text(ND), ND_CANON)["verdict"] == "nap-incomplete")
for label, canon in (("wrong zip", dict(ND_CANON, address="100 Example, Exampleton, KY 40001")), ("wrong city", dict(ND_CANON, address="100 Example, Otherville, KY 40000")),
                     ("wrong state", dict(ND_CANON, address="100 Example, Exampleton, TN 40000")), ("wrong street", dict(ND_CANON, address="102 Example, Exampleton, KY 40000"))):
    check("N3 %s -> mismatch, never match" % label, R.compare(claim.html_to_text(ND), canon, ND)["verdict"] == "mismatch", R.compare(claim.html_to_text(ND), canon, ND))
nostate = ND.replace('<div class="state-selector">KY</div>', "").replace('<div class="zip-code-selector">40000</div>', "")
check("N4 street + city only in markup (no state/zip) -> nap-incomplete", R.compare(claim.html_to_text(nostate), ND_CANON, nostate)["verdict"] == "nap-incomplete", R.compare(claim.html_to_text(nostate), ND_CANON, nostate))
ldj = '<script type="application/ld+json">{"@type":"LocalBusiness","name":"X","address":{"@type":"PostalAddress","streetAddress":"100 Example","addressLocality":"Exampleton","addressRegion":"KY","postalCode":"40000"}}</script>'
check("N5 generic JSON-LD PostalAddress parsed", R.structured_address(ldj) == {"street": "100 Example", "city": "Exampleton", "state": "KY", "zip": "40000"}, R.structured_address(ldj))
q2 = os.path.join(TMP, "nd.json")
json.dump({"canonical": ND_CANON, "create_rows": [{"id": "create-nd", "directory": "nextdoor.com", "state": "needs-human", "mike_approval": None, "evidence_url": None, "history": []}]}, open(q2, "w"))
db2, fp2 = FakeDB(), FakePortal()
rec2 = lambda *a, **k: T.record_transition(*a, portal=fp2, activities=fp2, verification=fp2, directories=db2, **k)
ch2 = dict(chk(), directory="nextdoor.com", url="https://nextdoor.com/pages/x/", nap_shown="Alder Care Consulting & Solutions | 100 Example | (502) 555-0101")
r2 = PR.proof_step([ch2], DAY, queue_path=q2, db=db2, record=rec2, reader=lambda u, cn: R.compare(claim.html_to_text(ND), cn, ND))
check("N6 proof_step moves the nextdoor page shape (sanitized to the test identity) live", len(r2["moved"]) == 1 and json.load(open(q2))["create_rows"][0]["state"] == "live", r2)

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
