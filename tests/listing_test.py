"""Listing URL / NAP error / honest-state tests (placeholder identity, no network). Run: python tests/listing_test.py  (CI does this).

L1 permalink resolution   L2 napConsistent null on unchecked   L3 reasons   L4 pctFound over checked only   L5 NAP error field/live/right
L6 scope + no Directory or portal-seed call in this path
"""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import listing as L  # noqa: E402
import portal as P  # noqa: E402

ok = []
def check(name, cond, detail=""):
    ok.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)

NAME = "Alder Care Consulting & Solutions"
PH = ["5025550101"]
def lk(href, text="", card=""): return {"href": href, "text": text, "aria": "", "card": card}

# L1: a YP/Superpages/DexKnows matched page is a guessed-slug search list; the record link on it is the listing.
yp_guess = "https://www.yellowpages.com/exampleton-ky/alder-care-consulting-solutions"
yp_links = [lk("https://www.yellowpages.com/nationwide/mip/life-alert-100000001?lid=1", "Life Alert"),
            lk("https://www.yellowpages.com/exampleton-ky/mip/alder-care-consltng-solutions-123456789", "Alder Care Consltng-Solutions"),
            lk(yp_guess + "#", "Continue")]
check("L1 YP: guessed slug resolves to the /mip/ record page", L.resolve("yellowpages.com", yp_guess, yp_links, NAME, PH) == ("https://www.yellowpages.com/exampleton-ky/mip/alder-care-consltng-solutions-123456789", "listing"))
sp = [lk("https://www.superpages.com/exampleton-ky/bpp/alder-care-consltng-solutions-123456789", "Alder Care Consltng-Solutions"), lk("https://www.superpages.com/bpp/123456789/directions", "Directions")]
check("L1 Superpages: /bpp/ record page", L.resolve("superpages.com", "https://www.superpages.com/exampleton-ky/alder-care-consulting-solutions", sp, NAME, PH)[0].endswith("/bpp/alder-care-consltng-solutions-123456789"))
dx = [lk("https://www.dexknows.com/exampleton-ky/bp/alder-care-consltng-solutions-123456789", "Alder Care Consltng-Solutions"), lk("https://www.dexknows.com/listings/123456789/gallery?lid=123456789", "Photos")]
check("L1 DexKnows: /bp/ record page", L.resolve("dexknows.com", "https://www.dexknows.com/exampleton-ky/alder-care-consulting-solutions", dx, NAME, PH)[0].endswith("/bp/alder-care-consltng-solutions-123456789"))
mc = [lk("https://www.merchantcircle.com/alder-care-consulting-solutions-exampleton-ky?cgp=", "Alder Care Consulting & Solutions")]
check("L1 MerchantCircle: category page resolves to the business page (query stripped)", L.resolve("merchantcircle.com", "https://www.merchantcircle.com/ky-exampleton/health-and-beauty/care-providers/assisted-living", mc, NAME, PH) == ("https://www.merchantcircle.com/alder-care-consulting-solutions-exampleton-ky", "listing"))
hf = [lk("https://www.hotfrog.com/company/AJm/alder-care-consulting-solutions/exampleton/hospice", "Alder Care Consulting & Solutions")]
check("L1 Hotfrog: search page resolves to /company/ page", L.resolve("hotfrog.com", "https://www.hotfrog.com/search/Exampleton%2C%20KY/Alder", hf, NAME, PH)[0].startswith("https://www.hotfrog.com/company/"))
n49 = [lk("https://www.n49.com/biz/100000002/alder-care-ky-exampleton/", "Alder Care Consulting & Solutions")]
check("L1 n49: search page resolves to /biz/ page", L.resolve("n49.com", "https://www.n49.com/search/Alder/1/exampleton-kentucky/", n49, NAME, PH)[0] == "https://www.n49.com/biz/100000002/alder-care-ky-exampleton/")
check("L1 Bing search-only match -> None + 'search'", L.resolve("bing.com", "https://www.bing.com/maps/search?q=Alder+Care", [], NAME, PH) == (None, "search"))
check("L1 Apple search-only match -> None + 'search'", L.resolve("maps.apple.com", "https://maps.apple.com/?q=Alder&near=Exampleton", [], NAME, PH) == (None, "search"))
check("L1 Google /maps/search is not a listing", L.resolve("google.com", "https://www.google.com/maps/search/Alder+Care", [], NAME, PH) == (None, "search"))
check("L1 Google /maps/place is a listing", L.resolve("google.com", "https://www.google.com/maps/place/Alder+Care/@1,2,17z/data=x", [], NAME, PH)[1] == "listing")
check("L1 Apple place-id page is a listing", L.resolve("maps.apple.com", "https://maps.apple.com/place?place-id=I302&address=x", [], NAME, PH)[1] == "listing")
check("L1 a link to ANOTHER business is never taken", L.resolve("yellowpages.com", yp_guess, [yp_links[0]], NAME, PH) == (None, "search"))
check("L1 a page that is already the record is kept", L.resolve("mapquest.com", "https://www.mapquest.com/us/kentucky/alder-care-716689036", [], NAME, PH) == ("https://www.mapquest.com/us/kentucky/alder-care-716689036", "listing"))
for d, u in (("yellowpages.com", yp_guess), ("hotfrog.com", "https://www.hotfrog.com/search/x"), ("n49.com", "https://www.n49.com/search/x/1/y/"),
             ("merchantcircle.com", "https://www.merchantcircle.com/ky-exampleton/health-and-beauty/care-providers/assisted-living"), ("bing.com", "https://www.bing.com/maps/search?q=x")):
    check("L1 is_permalink rejects %s search/category/guessed URL" % d, not L.is_permalink(d, u))

# payload: a stored search URL (old data) can never reach the portal as a url
def row(d, res, **k): return dict(biz="SCC", directory=d, result=res, url=k.get("url"), method="m", note=k.get("note"), diffs=k.get("diffs"))
DIRS = ["yellowpages.com", "bing.com", "maps.apple.com", "hotfrog.com", "mapquest.com", "brownbook.net", "yellowbook.com", "localstack.com", "facebook.com",
        "nextdoor.com", "foursquare.com", "yelp.com", "cybo.com", "manta.com", "bbb.org", "ezlocal.com"]
checks = [
    row("yellowpages.com", "found", url="https://www.yellowpages.com/exampleton-ky/mip/alder-care-123456789", diffs=[{"field": "name", "live": "Alder Care Consltng-Solutions", "canonical": NAME}]),
    row("bing.com", "found", url="https://www.bing.com/maps/search?q=Alder", diffs=[{"field": "phone", "live": "(502) 555-0199", "canonical": "(502) 555-0101"}]),
    row("maps.apple.com", "found", url="https://maps.apple.com/?q=Alder", diffs=[]),
    row("hotfrog.com", "found", url="https://www.hotfrog.com/search/Exampleton/Alder", diffs=[]),
    row("mapquest.com", "found", url="https://www.mapquest.com/us/kentucky/alder-716689036", diffs=[]),
    row("brownbook.net", "unsearchable", note="unsearchable"), row("yellowbook.com", "couldnt_check", note="no usable result"), row("localstack.com", "couldnt_check", note="blocked"),
    row("facebook.com", "couldnt_check", note="blocked"), row("nextdoor.com", "couldnt_check", note="blocked"), row("foursquare.com", "couldnt_check", note="error"),
    row("yelp.com", "couldnt_check", note="blocked"), row("cybo.com", "couldnt_check", note="no usable result"), row("manta.com", "couldnt_check", note="blocked"),
    row("bbb.org", "absent"), row("ezlocal.com", "couldnt_check", note="no usable result"),
]
p = P.build_payload(checks, "2026-10-19"); D = {d["domain"]: d for d in p["directories"]}
check("L1 payload: YP keeps the /mip/ permalink with urlKind listing", (D["yellowpages.com"]["url"], D["yellowpages.com"]["urlKind"]) == ("https://www.yellowpages.com/exampleton-ky/mip/alder-care-123456789", "listing"))
check("L1 payload: Bing search URL -> url null, urlKind search", (D["bing.com"]["url"], D["bing.com"]["urlKind"]) == (None, "search"))
check("L1 payload: Apple search URL -> url null, urlKind search", (D["maps.apple.com"]["url"], D["maps.apple.com"]["urlKind"]) == (None, "search"))
check("L1 payload: Hotfrog search URL -> url null, urlKind search", (D["hotfrog.com"]["url"], D["hotfrog.com"]["urlKind"]) == (None, "search"))
check("L1 payload: no found row's url is a search/category URL", all(d["url"] is None or L.is_permalink(d["domain"], d["url"]) for d in p["directories"]))
check("L1 payload: every non-found row has url null and urlKind null", all(d["url"] is None and d["urlKind"] is None for d in p["directories"] if d["state"] != "live"))

# L2
unchecked = [d for d in p["directories"] if d["state"] == "couldnt_check"]
check("L2 every couldn't-check row has napConsistent None (not False)", unchecked and all(d["napConsistent"] is None for d in unchecked))
check("L2 absent row napConsistent None", D["bbb.org"]["napConsistent"] is None)
check("L2 found rows are strictly True/False", all(isinstance(D[x]["napConsistent"], bool) for x in ("yellowpages.com", "bing.com", "maps.apple.com")))
check("L2 correct counts only found+True; found = correct + withNapErrors", (p["found"], p["correct"], p["withNapErrors"]) == (5, 3, 2))

# L3
R = {d: D[d]["reason"] for d in D}
check("L3 brownbook unsearchable", R["brownbook.net"] == "unsearchable")
check("L3 yellowbook + localstack no public search", R["yellowbook.com"] == R["localstack.com"] == "no public search")
check("L3 facebook, nextdoor, foursquare login required (even when the visit errored)", R["facebook.com"] == R["nextdoor.com"] == R["foursquare.com"] == "login required")
check("L3 yelp + cybo bot wall", R["yelp.com"] == R["cybo.com"] == "bot wall")
check("L3 other walled directory -> bot wall; unreadable -> no usable result", R["manta.com"] == "bot wall" and R["ezlocal.com"] == "no usable result")
check("L3 every unchecked row has plain-English reasonText, no 'blocked or unavailable'", all(d["reasonText"] and "blocked or unavailable" not in d["reasonText"] for d in unchecked))
check("L3 found/absent rows carry no reason", all(D[x]["reason"] is None for x in ("yellowpages.com", "bbb.org")))

# L4
check("L4 pctFound is found/(found+absent) over checked rows only: 5 of 6 = 83, not 100", (p["pctFound"], p["checked"], p["pctFoundBasis"]) == (83, 6, "checked"))
all_unchecked = P.build_payload([row("yelp.com", "couldnt_check", note="blocked")], "2026-10-19")
check("L4 nothing checked -> pctFound None (not 0, not 100)", all_unchecked["pctFound"] is None and all_unchecked["checked"] == 0)

# L5
e = D["bing.com"]["napErrors"]
check("L5 NAP error row carries field, live value and right value", e == [{"field": "phone", "live": "(502) 555-0199", "right": "(502) 555-0101"}])
check("L5 name error carries live + right", D["yellowpages.com"]["napErrors"][0]["right"] == NAME and "Consltng" in D["yellowpages.com"]["napErrors"][0]["live"])
check("L5 correct row has no napErrors; unchecked row has none", D["mapquest.com"]["napErrors"] == [] and D["facebook.com"]["napErrors"] == [])

# L6
check("L6 scope numbers in payload: 25 of 86", (p["directoriesChecked"], p["catalogTotal"]) == (25, 86))
psrc = open(os.path.join(HERE, "..", "job", "portal.py"), encoding="utf-8").read(); lsrc = open(os.path.join(HERE, "..", "job", "listing.py"), encoding="utf-8").read()
check("L6 listing.py and portal.py make no network, browser or Directory call", not any(w in lsrc for w in ("urllib.request", "urlopen", "requests", "playwright", "subprocess", "socket", "import core", "import discover")))
check("L6 no portal-seed or Directory import in portal.py", not any(w in psrc for w in ("import core", "import discover", "owned_chrome", "seed-nm", "subprocess")))

# backfill path stays offline
import tempfile, run as jobrun  # noqa: E402
td = tempfile.mkdtemp()
json.dump([{"biz": "SCC", "directory": "yellowpages.com", "url": yp_guess, "text": "x", "links": yp_links}], open(os.path.join(td, "pages.local.json"), "w"))
rr = jobrun.reresolve_urls([row("yellowpages.com", "found", url=yp_guess, diffs=[])], td)
check("L1 backfill re-resolves a stored guessed-slug URL from saved page links (offline)", rr[0]["url"].endswith("/mip/alder-care-consltng-solutions-123456789"))
check("L6 reresolve_urls source has no network call", "urlopen" not in __import__("inspect").getsource(jobrun.reresolve_urls))

print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})")
sys.exit(0 if all(ok) else 1)
