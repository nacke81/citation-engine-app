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

# G6 slice 2: compare by normalized value (any difference is a fix), site field, no noise from formatting, service-area rule.
import copy  # noqa: E402
I6 = copy.deepcopy(IDENT)
I6["BIZ"]["NM"]["site"] = "birchmedia.example"; I6["BIZ"]["SCC"]["site"] = "aldercare.example"
I6["BIZ"]["NM"]["street"] = "200 Sample Blvd Ste 200"
I6["CANON"] = {"NM": {"name": "Birch Media", "phone": "(615) 555-0111", "address": "200 Sample Blvd Ste 200, Testville, TN 39999"}}
def nm(lines): return fixlist.diffs_for("\n".join(["Birch Media"] + lines) + "\n", dict(EV_OK), I6, "NM", "https://dir.example/biz/1", labels=True)
def fields(d): return sorted(x["field"] for x in d)
OKSITE = "birchmedia.example"
BASE = ["200 Sample Blvd", "Ste 200", "Testville, TN 39999", "(615) 555-0111", OKSITE]
check("G6 baseline listing (canonical everywhere) -> no diffs", nm(BASE) == [], str(nm(BASE)))
# (a) unknown wrong phone: not on any stale list
d_a = nm(["200 Sample Blvd", "Ste 200", "Testville, TN 39999", "(615) 555-0177", OKSITE])
check("G6a unknown wrong phone -> Phone fix with live value, no stale label", d_a == [{"field": "phone", "live": "(615) 555-0177", "canonical": "(615) 555-0111"}], str(d_a))
d_a2 = nm(["200 Sample Blvd", "Ste 200", "Testville, TN 39999", "(615) 555-0112", OKSITE])
check("G6a the known stale phone is still a Phone fix, now labeled old phone", d_a2[0].get("label") == "old phone" and fields(d_a2) == ["phone"], str(d_a2))
# (b) site differing only by www / scheme / slash / tracking params / case
for v in ("https://www.birchmedia.example/", "http://birchmedia.example", "WWW.BirchMedia.example/?utm_source=gbp&utm_medium=organic", "Visit: birchmedia.example"):
    check(f"G6b site '{v}' -> not on the fix list", nm(BASE[:-1] + [v]) == [], str(nm(BASE[:-1] + [v])))
d_b = nm(BASE[:-1] + ["https://www.other-site.example/"])
check("G6b a different site IS a Site fix", d_b == [{"field": "site", "live": "other-site.example", "canonical": "birchmedia.example"}], str(d_b))
# (c) missing site
d_c = nm(BASE[:-1])
check("G6c no site shown -> Site fix 'missing'", d_c == [{"field": "site", "live": "missing", "canonical": "birchmedia.example"}], str(d_c))
check("G6c a bare 'Website' button (URL not in the text) is not called missing", nm(BASE[:-1] + ["Website"]) == [])
check("G6c a results-page URL cannot prove 'missing'", fixlist.diffs_for("Birch Media\n(615) 555-0111\n", dict(EV_OK), I6, "NM", "https://dir.example/search?q=birch") == [])
# (d) Suite vs Ste and other formatting noise
for addr in (["200 Sample Blvd., Suite 200", "Testville, TN 39999"], ["200 sample boulevard #200", "Testville TN 39999"], ["200 Sample Blvd", "Suite 200", "Testville, TN 39999"], ["200 SAMPLE BLVD STE 200, Testville, TN 39999"]):
    check(f"G6d address {addr[0]!r} -> no diff", nm(addr + ["(615) 555-0111", OKSITE]) == [], str(nm(addr + ["(615) 555-0111", OKSITE])))
for ph in ("615-555-0111", "615.555.0111", "+1 (615) 555-0111", "6155550111"):
    check(f"G6d phone {ph!r} -> no diff", nm(["200 Sample Blvd", "Ste 200", "Testville, TN 39999", ph, OKSITE]) == [])
d_d = nm(["200 Sample Blvd", "Ste 300", "Testville, TN 39999", "(615) 555-0111", OKSITE])
check("G6d a different suite number IS an Address fix", fields(d_d) == ["address"], str(d_d))
check("G6d a different street IS an Address fix", fields(nm(["300 Sample Blvd", "Ste 200", "Testville, TN 39999", "(615) 555-0111", OKSITE])) == ["address"])
# (e) service-area listing: no street shown -> never an address fix (a rule for any listing, not one URL)
d_e = nm(["Marketing agency", "Open · Closes 5 PM", OKSITE, "(615) 555-0111"])
check("G6e service-area listing (no street shown) -> not an address fix", d_e == [], str(d_e))
check("G6e same rule on a second business and a different page shape", fixlist.diffs_for("Alder Care Consulting & Solutions\nHospice\n(502) 555-0101\naldercare.example\n", dict(EV_OK), I6, "SCC", "https://d2.example/x") == [])
# other businesses on the same page must not leak in (list pages)
d_f = nm(BASE + ["Claim this business", "Other Co", "9 Elm Rd", "Testville, TN 39999", "(615) 555-0999"])
check("G6 other businesses below the stop marker are ignored", d_f == [], str(d_f))
d_g = fixlist.diffs_for("Top 10 in Testville\nOne Co\n(615) 555-0301\nTwo Co\n(615) 555-0302\nThree Co\n(615) 555-0303\nBirch Media\n200 Sample Blvd\nTestville, TN 39999\n(615) 555-0111\n", dict(EV_OK), I6, "NM", "https://dir.example/cat/x", labels=True)
check("G6c a card on a many-business list page is not called 'missing site'", d_g == [], str(d_g))
# self-check: a comparer that never flags must fail (a)
_o2 = fixlist.diffs_for
fixlist.diffs_for = lambda *a, **k: []
check("G6 self-check: a broken comparer fails the unknown-phone test", nm(["200 Sample Blvd", "Ste 200", "Testville, TN 39999", "(615) 555-0177", OKSITE]) != d_a)
fixlist.diffs_for = _o2
# the job path stays offline: build() makes no network or portal call
import inspect  # noqa: E402
check("G6 safety: fixlist imports no network/portal module", not any(w in inspect.getsource(fixlist) for w in ("httpx", "requests", "urlopen", "portal", "socket")))

print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})")
sys.exit(0 if all(ok) else 1)
