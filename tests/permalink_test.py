"""Permalink gate tests (placeholder identity, no network). Run: python tests/permalink_test.py  (CI does this).

P1 known-good listing URLs pass     P2 known-bad search/category URLs fail     P3 unknown host: passes if not searchy, flagged unverified
P4 saved-run fixture: 0 found rows with a searchy or category URL after the gate, nothing silently dropped
P5 build() flips a bad found row to couldnt_check "no permalink", keeps the rejected URL, never found with a bad URL
P6 dedup: the method whose URL passes the gate wins     P7 no Directory, portal or network call in this path
"""
import json, os, sys, re
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
sys.path.insert(0, os.path.join(HERE, "..", "job"))

ok = []
def check(name, cond, detail=""):
    ok.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)

try:
    import permalink as PL
except ImportError as e:
    print("FAIL permalink module missing:", e); sys.exit(1)

GOOD = [
    ("yellowpages.com", "https://www.yellowpages.com/exampleton-ky/mip/alder-care-consltng-solutions-123456789"),
    ("superpages.com", "https://www.superpages.com/exampleton-ky/bpp/alder-care-consltng-solutions-123456789"),
    ("dexknows.com", "https://www.dexknows.com/exampleton-ky/bp/alder-care-consltng-solutions-123456789"),
    ("merchantcircle.com", "https://www.merchantcircle.com/alder-care-consulting-solutions-exampleton-ky"),
    ("cybo.com", "https://www.cybo.com/US-biz/alder-care-consulting-solutions"),
    ("hotfrog.com", "https://www.hotfrog.com/company/AJxxxxxxxxxxxxxxxxxxxx/alder-care-consulting-solutions/exampleton/hospice-home-health-care"),
    ("facebook.com", "https://www.facebook.com/p/Alder-Care-Consulting-and-Solutions-LLC-61554027512962/"),
    ("facebook.com", "https://www.facebook.com/BirchMedia/"),
    ("google.com", "https://www.google.com/maps/place/alder-care/@1.5,1.5,17z/data=!3m1!4b1?entry=ttu"),
    ("mapquest.com", "https://www.mapquest.com/us/kentucky/alder-care-consltng-solutions-123456789"),
    ("n49.com", "https://www.n49.com/biz/1234567/alder-care/exampleton"),
    ("yellowbot.com", "https://www.yellowbot.com/birch-media-exampleton-tn.html"),
    ("maps.apple.com", "https://maps.apple.com/place?place-id=IPLACE0001&name=alder-care"),
    ("bing.com", "https://www.bing.com/maps/search?style=r&ss=id.local_ypid%3A%22YN0000000001%22&q=alder-care"),
]
BAD = [
    ("yellowpages.com", "https://www.yellowpages.com/exampleton-ky/alder-care-consulting-solutions"),
    ("superpages.com", "https://www.superpages.com/exampleton-ky/alder-care-consulting-solutions"),
    ("dexknows.com", "https://www.dexknows.com/exampleton-ky/alder-care-consulting-solutions"),
    ("google.com", "https://www.google.com/maps/search/alder-care+exampleton+ky"),
    ("google.com", "https://www.google.com/search?q=alder-care"),
    ("maps.apple.com", "https://maps.apple.com/?q=alder-care&near=exampleton"),
    ("bing.com", "https://www.bing.com/maps/search?q=alder-care+exampleton"),
    ("merchantcircle.com", "https://www.merchantcircle.com/ky-exampleton/health-and-beauty/care-providers/assisted-living"),
    ("merchantcircle.com", "https://www.merchantcircle.com/ky-exampleton/health-and-beauty/care-providers"),
    ("hotfrog.com", "https://www.hotfrog.com/search/exampleton%2C%20KY/alder-care-consulting-solutions"),
    ("n49.com", "https://www.n49.com/search/alder-care-consulting/55555/exampleton-ky/"),
    ("yelp.com", "https://www.yelp.com/search?find_desc=alder-care&find_loc=exampleton"),
    ("facebook.com", "https://www.facebook.com/search/pages?q=alder-care"),
    ("facebook.com", "https://www.facebook.com/public/Alder-Care"),
    ("cybo.com", "https://www.cybo.com/US/exampleton/"),
    ("mapquest.com", "https://www.mapquest.com/search/results?query=alder-care"),
    ("yellowbot.com", "https://www.yellowbot.com/search?q=alder&place=exampleton"),
    ("yellowpages.com", ""),
]
for d, u in GOOD:
    r = PL.is_permalink(d, u)
    check(f"P1 good passes: {d} {u[:70]}", isinstance(r, tuple) and r[0] is True, str(r))
for d, u in BAD:
    r = PL.is_permalink(d, u)
    check(f"P2 bad fails: {d} {u[:70]}", isinstance(r, tuple) and r[0] is False and r[1], str(r))

# P3 host with no known shape
okx, why = PL.is_permalink("manta.com", "https://www.manta.com/c/m0abc12/alder-care")
check("P3 unknown host, not searchy: passes", okx is True)
check("P3 unknown host is flagged unverified", PL.is_verified_shape("manta.com") is False and PL.is_verified_shape("yellowpages.com") is True)
check("P3 unknown host, searchy: fails", PL.is_permalink("manta.com", "https://www.manta.com/search?search=alder")[0] is False)
c = {"result": "found", "directory": "manta.com", "url": "https://www.manta.com/c/m0abc12/alder-care"}
PL.apply_gate(c)
check("P3 apply_gate on unknown host keeps found + _permalink_unverified", c["result"] == "found" and c.get("_permalink_unverified") is True)

# P3b no-shape hosts also fail on a category path (one regex reused: listing.SEARCHY)
NOSHAPE = ["nextdoor.com", "manta.com", "foursquare.com", "bizapedia.com", "brownbook.net", "localstack.com", "yellowbook.com", "ezlocal.com", "showmelocal.com"]
check("P3b the 9 no-shape hosts really have no shape", all(not PL.is_verified_shape(h) for h in NOSHAPE))
for h in NOSHAPE:
    for cu in (f"https://www.{h}/category/plumbers", f"https://www.{h}/categories/plumbers/exampleton-ky"):
        r = PL.is_permalink(h, cu)
        check(f"P3b no-shape category fails: {h} {cu[-34:]}", r[0] is False and r[1], str(r))
    check(f"P3b no-shape record url still passes: {h}", PL.is_permalink(h, f"https://www.{h}/c/m0abc12/alder-care")[0] is True)
cx = {"result": "found", "directory": "manta.com", "url": "https://x.com/category/y"}
PL.apply_gate(cx)
check("P3b apply_gate flips a no-shape category row to couldnt_check no permalink", cx["result"] == "couldnt_check" and cx["note"] == "no permalink" and cx["_rejected_url"] == "https://x.com/category/y" and "_permalink_unverified" not in cx, str(cx))
_pl_src = "\n".join(l for l in open(os.path.join(HERE, "..", "job", "permalink.py"), encoding="utf-8").read().splitlines() if not l.strip().startswith("#"))
check("P3b one regex reused (listing.SEARCHY), no third category regex in permalink.py", "listing.SEARCHY" in _pl_src and not re.search(r"re\.compile\(.*categor", _pl_src) and "|/categor" not in _pl_src)

# P4 saved-run fixture
fx = [json.loads(l) for l in open(os.path.join(HERE, "fixtures", "found-rows-20261018-1100.jsonl"), encoding="utf-8") if l.strip()]
check("P4 fixture has the SCC + NM found rows", len(fx) == 34 and {r["biz"] for r in fx} == {"SCC", "NM"}, str(len(fx)))
CATEGORY = re.compile(r"(?i)/search|[?&](q|query|search|search_terms|find_desc|find_text|what)=|/explore|/maps/search|/category|/categories|/[a-z]{2}-[a-z\-]+/[a-z\-]+/")
out = []
for r in fx:
    c = {"biz": r["biz"], "directory": r["dir"], "result": "found", "url": r["url"], "method": r["method"]}
    PL.apply_gate(c); out.append(c)
check("P4 no row dropped", len(out) == len(fx))
bad_found = [c for c in out if c["result"] == "found" and (PL.SEARCHY_URL_RE.search(c["url"]) and "local_ypid" not in c["url"] or (c["directory"] == "merchantcircle.com" and CATEGORY.search(c["url"])))]
check("P4 0 found rows with a searchy or category URL after the gate", not bad_found, str(bad_found))
flipped = [c for c in out if c["result"] == "couldnt_check"]
check("P4 flipped rows carry note no permalink and the rejected URL", flipped and all(c["note"] == "no permalink" and c["_rejected_url"] and c["url"] is None for c in flipped), str(len(flipped)))
check("P4 mapquest stays found", all(c["result"] == "found" for c in out if c["directory"] == "mapquest.com"))
check("P4 google/apple/bing /place rows stay found", all(c["result"] == "found" for c in out if c["method"] == "chrome-mapsearch" and c["directory"] in ("google.com", "maps.apple.com", "bing.com")))
check("P4 slug rows on YP/SP/DK flip", all(c["result"] == "couldnt_check" for c in out if c["directory"] in ("yellowpages.com", "superpages.com", "dexknows.com")))

# P5 build() end to end (offline)
import run as jobrun  # noqa: E402
from cfg import DIRS  # noqa: E402
def row(**k):
    base = dict(kind="dir", method="chrome-pattern", status="found", url="", ev={"name": True, "street": True, "phones": ["x"]}, note="", log="", verified=False, results=0)
    base.update(k); return base
YP = "yellowpages.com"
rows = [row(biz="SCC", dir=YP, url="https://www.yellowpages.com/exampleton-ky/alder-care-consulting-solutions")]
_, built = jobrun.build(rows, {})
b = {(c["biz"], c["directory"]): c for c in built}
cy = b[("SCC", YP)]
check("P5 build: bad found URL becomes couldnt_check", cy["result"] == "couldnt_check", cy["result"])
check("P5 build: reason no permalink", cy["note"] == "no permalink", str(cy["note"]))
check("P5 build: stored url is None, rejected url kept", cy["url"] is None and cy["_rejected_url"].endswith("alder-care-consulting-solutions"))
check("P5 build: no match or diff fields on the flipped row", not cy["match"] and cy["diffs"] is None)
check("P5 build: row not dropped (still one row for the cell)", len([c for c in built if c["biz"] == "SCC" and c["directory"] == YP]) == 1)
good = "https://www.yellowpages.com/exampleton-ky/mip/alder-care-consltng-solutions-123456789"
_, built2 = jobrun.build([row(biz="SCC", dir=YP, url=good)], {})
cg = [c for c in built2 if c["biz"] == "SCC" and c["directory"] == YP][0]
check("P5 build: good URL stays found with its URL", cg["result"] == "found" and cg["url"] == good)

# P6 dedup in judge.combine
import judge  # noqa: E402
bad_row = row(biz="SCC", dir="merchantcircle.com", method="http-search", url="https://www.merchantcircle.com/ky-exampleton/health-and-beauty/care-providers/assisted-living")
good_row = row(biz="SCC", dir="merchantcircle.com", method="http-pattern", url="https://www.merchantcircle.com/alder-care-consulting-solutions-exampleton-ky")
for order in ([bad_row, good_row], [good_row, bad_row]):
    comb = judge.combine(order, DIRS, set())
    res, src = comb[("SCC", "merchantcircle.com")]
    check("P6 dedup keeps the passing URL (order %s)" % ("bad-first" if order[0] is bad_row else "good-first"), res == "found" and src["url"] == good_row["url"])
_, bb = jobrun.build([bad_row, good_row], {})
cm = [c for c in bb if c["biz"] == "SCC" and c["directory"] == "merchantcircle.com"][0]
check("P6 build with both methods: found with the permalink", cm["result"] == "found" and cm["url"] == good_row["url"])

# P7 offline
src_text = open(os.path.join(HERE, "..", "job", "permalink.py"), encoding="utf-8").read()
check("P7 permalink.py has no network or portal call", not re.search(r"urllib\.request|requests|playwright|import portal|socket|http\.client", src_text))
check("P7 runtime gate wired at build()", "permalink.apply_gate" in open(os.path.join(HERE, "..", "job", "run.py"), encoding="utf-8").read())

print(f"\n{sum(ok)}/{len(ok)} passed")
sys.exit(0 if all(ok) else 1)
