"""Resolver tests (placeholder identity, saved HTML fixtures, NO network). Run: python tests/resolver_test.py  (CI does this).

R1 plan: every in-scope search URL carries City, ST; one distinctive word first; superpages and yellowbot never use phone; no page=N built
R2 per Directory: search fixture -> picks the agreeing card (not the decoy), follows it, lands on the listing fixture, URL passes the gate, NAP read from THAT page
R3 no agreeing card, no follow     R4 pagination goes through the page's own Next link     R5 category / search page never accepted as the listing
R6 blocked page stays blocked with the exact blocker     R7 out of scope Directories and FAKE untouched     R8 run-level: resolve_found_rows + build() turn a flipped row back into found
R9 no portal, Directory write, login or new browser stack in resolver.py
"""
import json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
sys.path.insert(0, os.path.join(HERE, "..", "job"))
sys.path.insert(0, HERE)

ok = []
def check(name, cond, detail=""):
    ok.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)

import html as H
from urllib.parse import urljoin
import core, resolver, permalink, listing, judge, run as jobrun  # noqa: E402
from cfg import IDENT, DIRS  # noqa: E402
FX = os.path.join(HERE, "fixtures", "resolver")


def page(name):
    return open(os.path.join(FX, name), encoding="utf-8").read()


def result(src, url, status=200):
    """Same shape core.HttpFetcher.fetch returns, built from saved HTML (no network)."""
    links = []
    for m in re.finditer(r'(?is)<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', src):
        ctx = core.html_to_text(src[max(0, m.start() - 500):m.end() + 300])
        links.append({"href": urljoin(url, H.unescape(m.group(1))), "card": ctx[-500:], "text": " ".join(core.html_to_text(m.group(2)).split())[:80], "aria": ""})
    return core.Result(status, url, core.html_to_text(src), links)


class Fake:
    """routes: [(predicate(url), (html, final_url) or Result)]. Records every URL asked for."""
    def __init__(self, routes): self.routes, self.asked, self.ctx = routes, [], None
    def fetch(self, url, label=""):
        self.asked.append(url)
        for pred, out in self.routes:
            if pred(url):
                return out if isinstance(out, core.Result) else result(out[0], out[1])
        return core.Result(404, url, "Not found", [])


def routes_for(d):
    k = d.split(".")[0]
    s, l = page(k + "-search.html"), page(k + "-listing.html")
    card = [x["href"] for x in result(s, "https://" + d + "/").links if "Pine" not in x["text"] and resolver.card_agrees(x, "SCC", IDENT) and listing.is_permalink(d, x["href"])]
    return s, l, card


B = "SCC"
x = IDENT["BIZ"][B]

# R1 plan rules
for d in resolver.INSCOPE:
    for kind, u in resolver.plan(d, B, IDENT):
        check(f"R1 {d} {kind}: no built page=N", not re.search(r"[?&]page=\d", u), u)
        if kind not in ("box", "direct"):
            check(f"R1 {d} {kind}: City, ST carried", "Exampleton" in u and ("KY" in u), u)
check("R1 yellowpages ladder: one word, phone, short, name", [k for k, _ in resolver.plan("yellowpages.com", B, IDENT)] == ["word", "phone", "short", "name"])
check("R1 yellowpages first query is ONE word", re.search(r"search_terms=alder&", resolver.plan("yellowpages.com", B, IDENT)[0][1]) is not None, resolver.plan("yellowpages.com", B, IDENT)[0][1])
check("R1 yellowpages phone query is digits", "search_terms=5025550101&geo_location_terms=Exampleton%2C+KY" in resolver.plan("yellowpages.com", B, IDENT)[1][1], resolver.plan("yellowpages.com", B, IDENT)[1][1])
check("R1 superpages never phone (500s)", "phone" not in [k for k, _ in resolver.plan("superpages.com", B, IDENT)])
check("R1 yellowbot one word only", [k for k, _ in resolver.plan("yellowbot.com", B, IDENT)] == ["word"] and "place=Exampleton%2C+KY" in resolver.plan("yellowbot.com", B, IDENT)[0][1])
check("R1 hotfrog path is City%2C%20ST then query", resolver.plan("hotfrog.com", B, IDENT)[0][1].startswith("https://www.hotfrog.com/search/Exampleton%2C%20KY/alder"), resolver.plan("hotfrog.com", B, IDENT)[0][1])
check("R1 google uses maps/search name city st", resolver.plan("google.com", B, IDENT)[0][1].startswith("https://www.google.com/maps/search/Alder+Care+Consulting"))
check("R1 cybo uses the slug url", resolver.plan("cybo.com", B, IDENT)[0][1] == "https://www.cybo.com/US-biz/alder-care-consulting-solutions")
check("R1 n49 goes through the site form (box), not a built search url", resolver.plan("n49.com", B, IDENT)[0][0] == "box")
pinned = dict(IDENT, RESOLVER_WORDS={"SCC": {"superpages.com": "consltng"}})
check("R1 identity can pin the word (superpages consltng)", "search_terms=consltng&" in resolver.plan("superpages.com", B, pinned)[0][1])

# R2 per Directory: search fixture -> listing fixture
for d in resolver.INSCOPE:
    k = d.split(".")[0]
    s, l, cards = routes_for(d)
    sres = result(s, "https://www.%s/search?x=1" % d)
    pick = resolver.cards_to_follow(d, sres.url, sres.links, B, IDENT)
    if d in ("google.com", "cybo.com"):
        # google: the maps/search URL itself lands on /maps/place/ (one match). cybo: slug URL loads the listing.
        final = [h for h in cards][0] if cards else None
        routes = [(lambda u: True, (l, resolver.plan(d, B, IDENT)[0][1] if d == "cybo.com" else "https://www.google.com/maps/place/Alder+Care+Consulting+%26+Solutions/@1.5,1.5,17z/data=!3m1!4b1"))]
    else:
        listing_url = pick[0] if pick else None
        routes = [(lambda u: "/search" in u or u.rstrip("/") == "https://www.n49.com", (s, "https://www.%s/search?x=1" % d)), (lambda u, lu=listing_url: u == lu, (l, listing_url))]
    F = Fake(routes)
    sb = (lambda dd, bb, s=s: result(s, "https://www.n49.com/search/alder/1/exampleton-ky/")) if d == "n49.com" else None
    if d not in ("google.com", "cybo.com"):
        check(f"R2 {d}: exactly one card followed, the agreeing one, not the decoy", len(pick) == 1 and "pine" not in pick[0].lower() and "category" not in pick[0].lower() and "assisted-living" not in pick[0], str(pick))
    r = resolver.resolve_cell(F, d, B, IDENT, sb)
    check(f"R2 {d}: resolves found", r["status"] == "found", str(r["log"]))
    check(f"R2 {d}: URL passes the permalink gate", r["status"] == "found" and permalink.is_permalink(d, r["url"])[0] is True and listing.is_permalink(d, r["url"]), str(r["url"]))
    check(f"R2 {d}: NAP read from the listing page (name + street + phone)", r["status"] == "found" and r["ev"]["name"] and r["ev"]["street"] and bool(r["ev"]["phones"]), str(r["ev"]))
    check(f"R2 {d}: stored URL is the final URL after redirects", r["status"] == "found" and r["url"] == listing._clean(r["url"]) and r["url"].startswith("https://"))
    if d not in ("google.com", "cybo.com", "n49.com"):
        check(f"R2 {d}: the search fixture alone is NOT accepted as the listing", resolver._accept(d, B, result(s, "https://www.%s/search?x=1" % d), IDENT) is None)
    check(f"R2 {d}: listing fixture alone passes the page tell", resolver.is_listing_page(d, r["url"], result(l, r["url"]).text) if r["status"] == "found" else False)

# R3 no agreeing card, no follow
d = "yellowpages.com"
s = page("yellowpages-search.html")
decoy_only = re.sub(r'<li class="card"><h2><a href="[^"]*alder-care[^"]*">.*?</li>', "", s, flags=re.S)
F = Fake([(lambda u: "/search" in u, (decoy_only, "https://www.yellowpages.com/search?x=1")), (lambda u: "/mip/" in u, (page("yellowpages-listing.html"), "https://www.yellowpages.com/exampleton-ky/mip/alder-care-consltng-solutions-123456789"))])
r = resolver.resolve_cell(F, d, B, IDENT)
check("R3 decoy only: miss", r["status"] == "miss" and r["url"] is None, str(r["log"]))
check("R3 decoy only: no listing link was followed", not [u for u in F.asked if "/mip/" in u], str(F.asked))

# R4 pagination: the page's own Next link, never a built page=N
s2 = page("yellowpages-search.html")
p1 = decoy_only.replace("</ul>", '</ul><a href="/search?search_terms=alder&geo_location_terms=Exampleton%2C+KY&page=2">Next</a>')
lu = "https://www.yellowpages.com/exampleton-ky/mip/alder-care-consltng-solutions-123456789"
asked_plan = {u for _, u in resolver.plan(d, B, IDENT)}
F = Fake([(lambda u: "page=2" in u, (s2.replace('<a href="https://www.yellowpages.com/search?search_terms=alder&geo_location_terms=Exampleton%2C+KY&page=2">Next</a>', ""), "https://www.yellowpages.com/search?page=2")),
          (lambda u: "/search" in u, (p1, "https://www.yellowpages.com/search?x=1")), (lambda u: u == lu, (page("yellowpages-listing.html"), lu))])
r = resolver.resolve_cell(F, d, B, IDENT)
check("R4 found on page 2 through the Next anchor", r["status"] == "found" and r["url"] == lu, str(r["log"]))
built = [u for u in F.asked if "page=" in u and u not in asked_plan]
check("R4 the only page=2 fetch is the href of the page's own Next anchor", built == ["https://www.yellowpages.com/search?search_terms=alder&geo_location_terms=Exampleton%2C+KY&page=2"], str(built))
check("R4 next_page_link finds Next, ignores other links", resolver.next_page_link(d, "https://www.yellowpages.com/search", result(p1, "https://www.yellowpages.com/search").links).endswith("page=2") and resolver.next_page_link("superpages.com", "https://www.superpages.com/search", result(page("superpages-search.html"), "https://www.superpages.com/search").links) is None)

# R5 category / search page never accepted
mc = page("merchantcircle-search.html")
for u in ("https://www.merchantcircle.com/ky-exampleton/health-and-beauty/care-providers/assisted-living", "https://www.merchantcircle.com/search?q=alder&qn=Exampleton%2C+KY"):
    check("R5 merchantcircle category/search page not accepted: " + u[-40:], resolver._accept("merchantcircle.com", B, result(page("merchantcircle-listing.html"), u), IDENT) is None)
check("R5 a listing URL that still shows 'Results for' is not accepted", resolver._accept("yellowpages.com", B, result(page("yellowpages-search.html"), lu), IDENT) is None)
check("R5 a listing-shaped page with no NAP for this business is not accepted", resolver._accept("yellowpages.com", B, result(page("yellowpages-listing.html").replace("Alder Care", "Other Biz").replace("100 Example", "5 Elsewhere"), lu), IDENT) is None)

# R6 blocked stays blocked with the exact blocker
blk = core.Result(403, "https://www.dexknows.com/search?x=1", "Access denied. Complete this quick check to continue.", [])
F = Fake([(lambda u: True, blk)])
r = resolver.resolve_cell(F, "dexknows.com", B, IDENT)
check("R6 blocked: status blocked, no url", r["status"] == "blocked" and r["url"] is None, str(r))
check("R6 blocked: exact blocker text kept", r["blocker"] and r["blocker"].startswith("403 Access denied"), str(r["blocker"]))
check("R6 blocked: no retry flood (<= MAX_FETCHES)", len(F.asked) <= resolver.MAX_FETCHES, str(len(F.asked)))
check("R6 blocked: nothing clicked past it (only plan URLs asked)", all("/search" in u for u in F.asked))

# R7 out of scope + FAKE
for od in ("maps.apple.com", "bing.com", "facebook.com", "manta.com", "nextdoor.com", "foursquare.com", "bizapedia.com", "showmelocal.com", "brownbook.net", "yelp.com", "bbb.org", "mapquest.com"):
    F = Fake([]); r = resolver.resolve_cell(F, od, B, IDENT)
    check(f"R7 out of scope untouched: {od}", r["status"] == "miss" and r["note"] == "out of scope" and not F.asked and not resolver.in_scope(od))
F = Fake([]); r = resolver.resolve_cell(F, "yellowpages.com", "FAKE", IDENT)
check("R7 FAKE is never resolved", r["note"] == "out of scope" and not F.asked)

# R8 run-level wiring
def row(**k):
    base = dict(kind="dir", method="chrome-search", status="found", url="", ev={"name": True, "street": True, "phones": ["x"]}, note="", log="", verified=False, results=0)
    base.update(k); return base
bad = "https://www.yellowpages.com/exampleton-ky/alder-care-consulting-solutions"
rows = [row(biz="SCC", dir="yellowpages.com", url=bad), row(biz="SCC", dir="manta.com", url="https://www.manta.com/search?search=alder"), row(biz="FAKE", dir="yellowpages.com", url=bad)]
F = Fake([(lambda u: "/search" in u, (page("yellowpages-search.html"), "https://www.yellowpages.com/search?x=1")), (lambda u: u == lu, (page("yellowpages-listing.html"), lu))])
new = resolver.resolve_found_rows(rows, F, IDENT, DIRS)
check("R8 resolver adds one chrome-resolver row for the in-scope flipped cell only", [(r["biz"], r["dir"], r["method"]) for r in new] == [("SCC", "yellowpages.com", "chrome-resolver")], str([(r["biz"], r["dir"]) for r in new]))
check("R8 manta (out of scope) and FAKE got no resolver row and no fetch", not [u for u in F.asked if "manta" in u])
_, before = jobrun.build(rows, {})
_, after = jobrun.build(rows + [{k: v for k, v in r.items() if not k.startswith("_")} for r in new], {new[0]["url"]: new[0]["_text"]})
cb = [c for c in before if c["biz"] == "SCC" and c["directory"] == "yellowpages.com"][0]
ca = [c for c in after if c["biz"] == "SCC" and c["directory"] == "yellowpages.com"][0]
check("R8 before the resolver: couldnt_check no permalink (the gate)", cb["result"] == "couldnt_check" and cb["note"] == "no permalink")
check("R8 after the resolver: found with the listing permalink", ca["result"] == "found" and ca["url"] == lu, str((ca["result"], ca["url"])))
check("R8 manta still honest (out of scope, gate unchanged)", [c for c in after if c["directory"] == "manta.com" and c["biz"] == "SCC"][0]["result"] == "couldnt_check")
check("R8 resolver_step is wired before the claim read", "resolver_step(" in open(os.path.join(HERE, "..", "job", "run.py"), encoding="utf-8").read())
check("R8 CE_RESOLVER=0 turns it off", (lambda: (os.environ.__setitem__("CE_RESOLVER", "0"), jobrun.resolver_step("nofile", None, {}, {}, None))[1] == 0)())
os.environ.pop("CE_RESOLVER", None)
miss_rows = resolver.resolve_found_rows(rows, Fake([]), IDENT, DIRS)
check("R8 a miss adds no row (cell keeps today's path)", miss_rows == [])

# R9 safety
src = open(os.path.join(HERE, "..", "job", "resolver.py"), encoding="utf-8").read()
check("R9 resolver.py has no portal, Directory write, login or new browser", not re.search(r"import portal|import directories|urllib\.request|requests|httpx|sync_playwright|subprocess|\.fill\(|password|signup|claim\.|captcha", src, re.I), "")
check("R9 resolver.py builds no page= url", not re.search(r"page=\{|page=%|\"page=\"|\?page=", src))

print(f"\n{sum(ok)}/{len(ok)} passed")
sys.exit(0 if all(ok) else 1)
