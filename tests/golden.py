"""Golden tests 1-5 on scrubbed fixtures (placeholder identity). Each also has a self-check that proves the test CAN fail.
Run: python tests/golden.py   (CI does this). Exit 1 on any failure.

  G1 recall: >=80% of the fixture listings per business found, 0 wrong-business claims.
  G2 no false absent: absent only with a same-method positive control; a real listing is never absent.
  G3 hard negative: the same-name business in another city (every field differs) claims 0 for SCC.
  G4 negative control: a made-up business finds 0 on every fixture page; a Directory blocked on purpose = couldn't check.
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import core, judge  # noqa: E402
from cfg import DIRS, IDENT  # noqa: E402

FX = os.path.join(HERE, "fixtures")
MAN = json.load(open(os.path.join(FX, "manifest.json")))
ok = []
def check(name, cond, detail=""):
    ok.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)
def page(m): return open(os.path.join(FX, m["file"]), encoding="utf-8").read()

listings = [m for m in MAN if m["kind"] == "listing"]
hardnegs = [m for m in MAN if m["kind"] == "hardneg"]
check("fixtures exist", len(listings) >= 8 and len(hardnegs) >= 2, f"{len(listings)} listings, {len(hardnegs)} hard negatives")

# G1
by = {"SCC": [], "NM": []}
for m in listings: by[m["biz"]].append(core.judge_listing(page(m), m["biz"])[0])
for b, v in by.items():
    check(f"G1 recall {b}", v and sum(v) / len(v) >= 0.8, f"{sum(v)}/{len(v)}")
wrong = [m["file"] for m in listings if core.judge_listing(page(m), "SCC" if m["biz"] == "NM" else "NM")[0]]
check("G1 zero cross-business claims (SCC page never claimed for NM and back)", not wrong, str(wrong))
# the scrubbed page must give the same verdict the real page gave
check("G1 scrub kept the verdict (real == scrubbed)", all(core.judge_listing(page(m), m["biz"])[0] == m["real_verdict"] for m in listings))
# self-check: break the matcher, G1 must fail
_orig = core.judge_listing
core.judge_listing = lambda t, b: (False, {}, "broken")
check("G1 self-check: a broken matcher fails recall", not all(core.judge_listing(page(m), m["biz"])[0] for m in listings))
core.judge_listing = _orig

# G2: rows built from the fixtures
def row(**k):
    base = dict(kind="dir", method="chrome-search", status="noresult", verified=True, results=5, url="", ev=None, blocked_on_purpose=False)
    base.update(k); return base
d0, d1 = DIRS[4], DIRS[5]
rows = [row(biz="SCC", dir=d0, status="found", url="u"), row(biz="NM", dir=d0, status="noresult"),     # control found on d0 -> NM absent allowed
        row(biz="NM", dir=d1, status="noresult"),                                                      # no control on d1 -> couldn't check
        row(biz="SCC", dir=DIRS[6], status="noresult", verified=False),                                # unverified results page -> couldn't check
        row(biz="SCC", dir=DIRS[7], status="noresult", results=0)]                                     # zero results shown -> couldn't check
c = judge.combine(rows, DIRS, ())
check("G2 absent allowed with a positive control", c[("NM", d0)][0] == "absent")
check("G2 no control -> couldn't check, not absent", c[("NM", d1)][0] == "couldnt_check")
check("G2 unverified results page -> couldn't check", c[("SCC", DIRS[6])][0] == "couldnt_check")
check("G2 zero shown results -> couldn't check", c[("SCC", DIRS[7])][0] == "couldnt_check")
check("G2 a found listing is never absent", c[("SCC", d0)][0] == "found")
truth = {("SCC", d0): "found", ("NM", d0): "absent"}
check("G2 score: no false absent", judge.score(c, {("SCC", d0): "found", ("NM", d1): "found"}, ())["false_absent"] == [])
bad = judge.combine([row(biz="NM", dir=d0, status="noresult"), row(biz="SCC", dir=d0, status="found")], DIRS, ())
check("G2 self-check: a real listing called absent IS counted as a false absent", judge.score(bad, {("NM", d0): "found"}, ())["false_absent"] == [("NM", d0)])
c2 = judge.combine([row(biz="SCC", dir="brownbook.net", status="found")], DIRS, ("brownbook.net",))
check("G2 unsearchable label wins (set by the list, not the engine)", c2[("SCC", "brownbook.net")][0] == "unsearchable")

# G3
for m in hardnegs:
    check(f"G3 hard negative {m['directory']} claims 0 for SCC", core.judge_listing(page(m), "SCC")[0] is False)
check("G3 rows: both rejected -> pass", judge.hard_negative_ok([dict(kind="hardneg", status="rejected", url="x")] * 2, IDENT["HARDNEG_ID"]))
check("G3 self-check: one claimed -> fail", not judge.hard_negative_ok([dict(kind="hardneg", status="rejected", url="x"), dict(kind="hardneg", status="claimed", url="y" + IDENT["HARDNEG_ID"])], IDENT["HARDNEG_ID"]))

# G4
allpages = [page(m) for m in MAN]
check("G4 made-up business: 0 claims over every fixture page", not any(core.judge_listing(t, "FAKE")[0] for t in allpages), f"{len(allpages)} pages")
class Fx:
    def __init__(s, block=None): s.block = block
    def fetch(s, url, label=""):
        if s.block and s.block in url: return core.Result(None, url, "", [], "blocked-on-purpose")
        return core.Result(200, url, page(listings[0]), [])
F = Fx("yellowpages.com")
r = core.discover(F, "yellowpages.com", "FAKE", [("search", "https://www.yellowpages.com/search?q=x")], [])
check("G4 blocked Directory -> couldn't check", r["status"] == "couldnt")
r2 = core.discover(Fx(), "yellowpages.com", "FAKE", [("search", "https://www.yellowpages.com/search?q=x")], [])
check("G4 self-check: not blocked + no made-up match -> not found", r2["status"] != "found")
crow = [row(biz="SCC", dir="yellowpages.com", status="found"), row(biz="FAKE", dir="yellowpages.com", status="couldnt", blocked_on_purpose=True)]
cc = judge.combine(crow, DIRS, ())
check("G4 rows: blocked made-up cell is couldn't check and made-up finds 0", judge.blocked_ok(cc, crow) and judge.made_up_ok(cc))

# G5 fix list: a stale phone is reported with the right field; a matching listing is not; old street is an address diff.
import fixlist  # noqa: E402
TXT_STALE = "Birch Media\n200 Sample, Testville, TN 39999\n(615) 555-0112\n"
TXT_OK = "Birch Media\n200 Sample, Testville, TN 39999\n(615) 555-0111\n"
TXT_OLD = "Birch Media\n900 Old Rd, Testville, TN 39999\n(615) 555-0111\n"
EV_STALE = dict(name=True, street=True, old_street=False, phones=[], stale_phone=True)
EV_OK = dict(name=True, street=True, old_street=False, phones=["6155550111"], stale_phone=False)
EV_OLD = dict(name=True, street=False, old_street=True, phones=["6155550111"], stale_phone=False)
d_stale = fixlist.diffs_for(TXT_STALE, EV_STALE, IDENT, "NM")
check("G5 stale phone -> one diff, field phone, live stale value, canonical value", d_stale == [{"field": "phone", "live": "(615) 555-0112", "canonical": "(615) 555-0111"}], str(d_stale))
check("G5 matching listing -> no diffs", fixlist.diffs_for(TXT_OK, EV_OK, IDENT, "NM") == [])
d_old = fixlist.diffs_for(TXT_OLD, EV_OLD, IDENT, "NM")
check("G5 old street -> field address", [d["field"] for d in d_old] == ["address"] and d_old[0]["live"].lower().startswith("900 old"), str(d_old))
check("G5 name variant on the page -> field name", [d["field"] for d in fixlist.diffs_for("1. Alder Care Conslting-Solutions\n100 Example\n", dict(EV_OK), IDENT, "SCC")] == ["name"])
check("G5 exact name -> no name diff", fixlist.diffs_for("1. Birch Media\n", dict(EV_OK), IDENT, "NM") == [])
# only found rows get diffs in the job output; couldn't-check / absent / unsearchable rows carry none
import run as jobrun  # noqa: E402
fr = [row(biz="NM", dir=DIRS[0], status="found", url="u1", ev=EV_STALE, method="chrome-pattern"),
      row(biz="NM", dir=DIRS[1], status="noresult"), row(biz="NM", dir=DIRS[2], status="couldnt")]
_, built = jobrun.build(fr, {"u1": TXT_STALE})
byd = {c["directory"]: c for c in built if c["biz"] == "NM"}
check("G5 job: found stale row carries a phone diff", [d["field"] for d in byd[DIRS[0]]["diffs"]] == ["phone"])
check("G5 job: couldn't-check cell has no diffs and is never absent", byd[DIRS[2]]["diffs"] is None and byd[DIRS[2]]["result"] == "couldnt_check")
_o = fixlist.diffs_for
fixlist.diffs_for = lambda *a, **k: []
check("G5 self-check: a broken extractor fails the stale-phone test", fixlist.diffs_for(TXT_STALE, EV_STALE, IDENT, "NM") != d_stale)
fixlist.diffs_for = _o

print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})")
sys.exit(0 if all(ok) else 1)
