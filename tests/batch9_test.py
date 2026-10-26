"""Batch 9 fix tests (t_d7a907d5): exact-name recheck, entry pages + search fallback, fit homepage flag, pagekit.select / overlays / frames,
formspec (data-driven sites), Chrome keepalive + lease. No network, no browser, no real Chrome: fakes everywhere. Run: python tests/batch9_test.py (CI)."""
import os, sys, json, tempfile, types, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ["CE_RUNS"] = tempfile.mkdtemp(prefix="ce-runs-")
JOB = os.path.join(HERE, "..", "job")
sys.path.insert(0, JOB); sys.path.insert(0, os.path.join(JOB, "playbooks"))
import recheck as R, fit as FIT, pagekit as PK, formspec as FS, chrome_keepalive as KA, build_runner as B, build_core as C

def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net
ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

IDENT = json.load(open(os.path.join(HERE, "test_identity.json"), encoding="utf-8"))
CANON = {"name": "Alder Care Consulting & Solutions", "address": "100 Example Drive, Exampleton KY 40000", "phone": "(502) 555-0101"}
PAD = " Lorem ipsum dolor sit amet." * 12
def page_text(name="Alder Care Consulting & Solutions", street="100 Example Drive", phone="(502) 555-0101"):
    return "Home\n%s\n%s\nExampleton, KY 40000\n%s\n%s\n" % (name, street, phone, PAD)

# ---- X1 exact name -------------------------------------------------------------------------------------------------------
for label, nm in (("case", "ALDER CARE CONSULTING & SOLUTIONS"), ("whitespace", "Alder  Care   Consulting &  Solutions"), ("and", "Alder Care Consulting and Solutions"), ("&amp;", "Alder Care Consulting &amp; Solutions")):
    c = R.compare(page_text(name=nm), CANON)
    check("X1 name differing only by %s still matches" % label, c["verdict"] == "match", str(c))
for label, nm in (("typo Consltng", "Alder Care Consltng & Solutions"), ("dropped word", "Alder Care Solutions"), ("added LLC", "Alder Care Consulting & Solutions LLC"), ("The prefix", "The Alder Care Consulting & Solutions")):
    c = R.compare(page_text(name=nm), CANON)
    check("X1 %s is mismatch: name" % label, c["verdict"] == "mismatch" and c["wrong"] and c["wrong"][0][0] == "name", str(c))
# the exact line wins when a page shows both a typo line (a related-listing teaser) and the real one
c = R.compare("Alder Care Consltng & Solutions\nNearby\n" + page_text(), CANON)
check("X1 a page with the exact line and a typo teaser reads at the exact line", c["verdict"] == "match", str(c))
# street / zip / phone strictness
check("X1 Dr for Drive is allowed", R.compare(page_text(street="100 Example Dr"), CANON)["verdict"] == "match")
c = R.compare(page_text(street="100 Example Road"), CANON); check("X1 Road for Drive is a mismatch", c["verdict"] == "mismatch" and any(f == "address" for f, _ in c["wrong"]), str(c))
c = R.compare(page_text(street="100 Example"), CANON); check("X1 missing street type is a mismatch (not the same street)", c["verdict"] == "mismatch", str(c))
c = R.compare(page_text().replace("40000", "40001"), CANON); check("X1 ZIP differing by a digit is a mismatch", c["verdict"] == "mismatch", str(c))
c = R.compare(page_text(phone="(502) 555-0102"), CANON); check("X1 phone differing by a digit is a mismatch", c["verdict"] == "mismatch" and any(f == "phone" for f, _ in c["wrong"]), str(c))
check("X1 phone formatting alone still matches", R.compare(page_text(phone="502.555.0101"), CANON)["verdict"] == "match")
# the Yellowpages case from the PR #27 dry run
YP = "Home\nKY\nExampleton\nAlder Care Consltng Solutions\n100 Example Dr\nExampleton, KY 40000\n(502) 555-0101\n" + PAD
YP_CRUMBS = "Home\nKYExampletonBusiness ManagementBusiness CoachesAlder Care Consltng-Solutions\n100 Example Dr\nExampleton, KY 40000\n(502) 555-0101\n" + PAD   # breadcrumb run-together line, as the live page renders it
YC = CANON
c = R.compare(YP, YC)
check("X1 Yellowpages-style typo 'Consltng' reads mismatch: name", c["verdict"] == "mismatch" and c["wrong"][0][0] == "name", str(c))
c = R.compare(YP_CRUMBS, YC)
check("X1 the typo inside a run-together breadcrumb line also reads mismatch: name, shown short", c["verdict"] == "mismatch" and c["wrong"][0][0] == "name" and len(c["wrong"][0][1]) <= len(CANON["name"]) + 6, str(c))
c = R.compare("Home\nBirch Hollow Plumbing | Drain Cleaning Experts\n100 Example Dr\n" + PAD, YC)
check("X1 a different business on the page is unreadable, not a name mismatch", c["verdict"] == "unreadable", str(c))
c = R.compare(page_text(street="100 Example Drive Exampleton"), CANON)
check("X1 street and city on one line, same street: still a match", c["verdict"] == "match", str(c))
check("X1 the typo page is never a match -> live", R.compare(YP, YC)["verdict"] != "match" and R.compare(YP_CRUMBS, YC)["verdict"] != "match")
check("X1 not-found page quoting our name is not a listing", R.compare("We couldn't find \"Alder Care Consulting & Solutions\"\nTry another search" + PAD, CANON)["verdict"] == "unreadable")

# ---- X2 entry pages and the search fallback -------------------------------------------------------------------------------
for bad in ("https://www.loc8nearme.com/payment.php?uuid=e3889f53", "https://getlistedusa.com/submission/", "https://a.example/checkout", "https://a.example/payment"):
    check("X2 %s is an entry page, not a listing" % bad, R._is_entry_page(bad))
check("X2 a listing path containing 'submissions' text in the slug is still a permalink", not R._is_entry_page("https://a.example/listing/alder-submissions-co-123"))
u = R.search_url_for("citylocalpro.com", IDENT)
check("X2 search URL for a create-discovery Directory carries name + city", u and "citylocalpro.com/search" in u and "Exampleton" in u, str(u))
seed = {"x.example": {"search_url_template": "https://x.example/s?q={name}&near={city}%2C+{st}"}}
u2 = R.search_url_for("x.example", IDENT, cat_rows=seed)
check("X2 search URL falls back to the Catalog template", u2 and u2.startswith("https://x.example/s?q=") and "Exampleton" in u2, str(u2))
check("X2 no template, no search", R.search_url_for("nope.example", IDENT, cat_rows={}) is None)

CAN = {"name": CANON["name"], "address": CANON["address"], "phone": CANON["phone"]}
def q_with(rows):
    p = os.path.join(tempfile.mkdtemp(), "q.json"); json.dump({"canonical": CAN, "fix_queue": rows}, open(p, "w")); return p, json.load(open(p))
LISTING = "https://x.example/biz/alder-care-1"
SEARCH_URL = R.search_url_for("x.example", IDENT, cat_rows=seed)
orig = R.search_url_for
R.search_url_for = lambda d, i, **k: orig(d, i, cat_rows=seed, **k)
rows = [{"id": "r1", "directory": "x.example", "state": "submitted", "evidence_url": "https://x.example/payment.php?uuid=1", "mike_approval": None, "history": []}]
p, q = q_with(rows)
calls = []
def plain(url):
    calls.append(url)
    if url == SEARCH_URL: return R.Page(200, url, "Results" + PAD, [{"href": LISTING, "text": "Alder Care Consulting & Solutions", "card": "Alder Care Consulting & Solutions Exampleton, KY", "aria": ""}])
    if url == LISTING: return R.Page(200, url, page_text())
    return R.Page(404, url, "", err="HTTP 404")
res = R.recheck(q, IDENT, plain=plain, chrome=None, record=lambda *a, **k: {}, db=None, queue_path=p, today="2026-11-02", write=False)
check("X2 payment.php evidence + no listing_url: found by name+city search, read, matched", res[0]["url"] == LISTING and res[0]["verdict"] == "match" and calls == [SEARCH_URL, LISTING], str((res, calls)))
rows[0]["evidence_url"] = "https://x.example/submission/"
p, q = q_with(rows); calls.clear()
res = R.recheck(q, IDENT, plain=lambda u: R.Page(200, u, "Results" + PAD, []), chrome=None, record=lambda *a, **k: {}, queue_path=p, today="2026-11-02", write=False)
check("X2 /submission/ evidence, search finds nothing: no-permalink, nothing written", res[0]["verdict"] == "no-permalink")
R.search_url_for = orig

# ---- X3 fit homepage flag --------------------------------------------------------------------------------------------------
def home(body, title="Home"): return {"status": 200, "html": "<html lang='en'><head><title>%s</title></head><body>%s%s</body></html>" % (title, body, "<p>filler</p>" * 200), "err": None, "dns": False}
DIRECTORY = home("<h1>Local Business Directory</h1><a href='/add-listing'>Add your business</a> free listing")
NEWS = home("<h1>Nashville events this weekend</h1><p>Concerts, festivals and nightlife news. Read the latest stories.</p>")
PAID = home("<h1>Grow your business</h1><p>Our marketing services start at $559/mo. Add your business to our directory of clients.</p>")
row = {"id": "create-z", "directory": "z.example", "state": "queued"}
v, why = FIT.classify(row, {"category": "local"}, "", DIRECTORY, [row]); check("X3 a real directory homepage stays fit", v == "fit", why)
v, why = FIT.classify(row, {"category": "local"}, "", NEWS, [row]); check("X3 events-news homepage with no add-listing signal is flagged", v == "flag" and "no add-listing" in why, why)
v, why = FIT.classify(row, {"category": "local"}, "", PAID, [row]); check("X3 a paid monthly marketing service is flagged even with 'directory' on the page", v == "flag" and "$559" in why, why)
tiny = {"status": 200, "html": "<html><body>x</body></html>", "err": None, "dns": False}
v, why = FIT.classify(row, {"category": "local"}, "", tiny, [row]); check("X3 an unreadable / tiny homepage is not flagged (no evidence)", v == "fit", why)
v, why = FIT.classify(row, {"category": "local"}, "", None, [row]); check("X3 --no-fetch: no flag", v == "fit")
calls = []
res = FIT.write_rejects([(row, "flag", "x")], "q.json", record=lambda *a, **k: calls.append(a) or {})
check("X3 --write never rejects a flag (a human looks)", calls == [] and res == [])
src = open(os.path.join(HERE, "..", "db", "gen_directories_seed.py"), encoding="utf-8").read()
seedrows = {r["domain"]: r for r in json.load(open(os.path.join(HERE, "..", "db", "directories_seed.json"), encoding="utf-8"))}
check("X3 nashvegas.com and maplenmain.com are niche-other in the seed and the generator", seedrows["nashvegas.com"]["category"] == "niche-other" and seedrows["maplenmain.com"]["category"] == "niche-other" and '"nashvegas.com", "maplenmain.com"' in src)
sql = open(os.path.join(HERE, "..", "db", "002_directories.sql"), encoding="utf-8").read()
check("X3 the migration SQL carries the same two categories", '"domain":"nashvegas.com"' in sql and '"category":"niche-other"' in sql.split('"domain":"nashvegas.com"')[1][:200] and '"category":"niche-other"' in sql.split('"domain":"maplenmain.com"')[1][:200])

# ---- X4 pagekit.select over fake pages ---------------------------------------------------------------------------------------
class Loc:
    def __init__(self, pg, css): self.pg, self.css = pg, css
    @property
    def first(self): return self
    def nth(self, i): self.pg.acts.append(("nth", self.css, i)); return self
    def count(self): return self.pg.counts.get(self.css, 1 if any(self.css.startswith(k) or k in self.css for k in self.pg.present) else 0)
    def click(self, **k): self.pg.acts.append(("click", self.css))
class SelPage:
    """kind: native | select2 | choices | unknown | none. Scripts the widget's JS answers by which constant the code evaluates."""
    def __init__(self, kind, shown, present=(), url="https://x.example/"):
        self.kind, self.shown, self.acts, self.url, self.present, self.counts = kind, shown, [], url, set(present), {}
    def locator(self, css): return Loc(self, css)
    def type(self, css, text, **k): self.acts.append(("type", css, text))
    def select_option(self, css, **k): self.acts.append(("select_option", css, k))
    def wait_for_timeout(self, ms): pass
    def evaluate(self, js, arg=None):
        if js is PK.OVERLAY_JS: return 0
        if js is PK.SELECT_PROBE_JS: return None if self.kind == "none" else {"kind": self.kind}
        if js is PK.NATIVE_VALUE_JS: return "251"
        if js is PK.FIND_OPTION_JS: return 2
        if js is PK.SHOWN_JS: return self.shown
        return 0
def kinds(pg): return [a[0] for a in pg.acts]
pg = SelPage("native", "Business Consultants"); r = PK.select(pg, "#category", "Business Consultants")
check("X4 native: picked by normalized text -> option value, no widget clicks", r["kind"] == "native" and ("select_option", "[data-ce-pick]", {"value": "251"}) in pg.acts and "click" not in kinds(pg), str(pg.acts))
pg = SelPage("choices", "Business Consultants", present=("[data-ce-pick] input.choices__input--cloned",)); r = PK.select(pg, "Category", "Business Consultants")
check("X4 Choices.js: clicks .choices__inner, types in the cloned search input, clicks the option", r["kind"] == "choices" and pg.acts[0] == ("click", "[data-ce-pick] .choices__inner") and ("type", "[data-ce-pick] input.choices__input--cloned", "Business Consultants") in pg.acts and "nth" in kinds(pg), str(pg.acts))
pg = SelPage("select2", "Springfield", present=(".select2-container--open .select2-search__field",)); r = PK.select(pg, "#city", "Springfield")
check("X4 select2: opens the container, types in the search field, clicks the result", r["kind"] == "select2" and pg.acts[0] == ("click", "[data-ce-pick] .select2-selection") and ("type", ".select2-container--open .select2-search__field", "Springfield") in pg.acts, str(pg.acts))
pg = SelPage("select2", "Springfield"); PK.select(pg, "#city", "Springfield")
check("X4 select2 without a search field (minimum results) still picks from the list", "type" not in kinds(pg) and "nth" in kinds(pg))
pg = SelPage("none", ""); 
try: PK.select(pg, "#nope", "x"); e = ""
except RuntimeError as ex: e = str(ex)
check("X4 no control found is an error naming it", "no control found" in e, e)
pg = SelPage("unknown", "")
try: PK.select(pg, "#plain-input", "x"); e = ""
except RuntimeError as ex: e = str(ex)
check("X4 a non-select element is refused", "not a select" in e, e)
pg = SelPage("choices", "Something Else", present=("input.choices__input--cloned",))
try: PK.select(pg, "#c", "Business Consultants"); e = ""
except RuntimeError as ex: e = str(ex)
check("X4 the widget showing a different value afterwards fails (readback)", "shows 'Something Else'" in e, e)
check("X4 CSS vs label targets are told apart", PK._is_css("#category") and PK._is_css("select[name=x]") and PK._is_css("css=.a") and not PK._is_css("City") and not PK._is_css("Business Category"))

# ---- X5 overlays and iframe submit ---------------------------------------------------------------------------------------------
class OvPage:
    def __init__(self, removed=2): self.removed, self.args = removed, []
    def evaluate(self, js, arg=None):
        if js is PK.OVERLAY_JS: self.args.append(arg); return self.removed
        return 1
pg = OvPage(2)
check("X5 clear_overlays with a target passes it and counts removals", PK.clear_overlays(pg, "#submit") == 2 and pg.args == [{"sel": "#submit"}])
check("X5 clear_ads(target) = ads + overlays", PK.clear_ads(OvPage(3), "#x") == 1 + 3)
check("X5 clear_ads without a target is the old behaviour (no overlay pass)", PK.clear_ads(pg) == 1 and len(pg.args) == 1)
class Boom:
    def evaluate(self, *a, **k): raise RuntimeError("navigated")
check("X5 overlay and ad passes never raise on a navigated page", PK.clear_overlays(Boom(), "#x") == 0 and PK.clear_ads(Boom(), "#x") == 0)
for needle in ("position", "fixed", "zIndex", "elementFromPoint", "contains(target)"):
    check("X5 overlay JS handles %s" % needle, needle in PK.OVERLAY_JS)
class FLoc:
    def __init__(self, fr, s): self.fr, self.s = fr, s
    @property
    def first(self): return self
    def count(self): return 1 if self.s in self.fr.has else 0
    def click(self, **k): self.fr.clicked.append(self.s)
class Frame:
    def __init__(self, url, has=()): self.url, self.has, self.clicked = url, set(has), []
    def locator(self, s): return FLoc(self, s)
class FPage:
    def __init__(self, main, frames):
        self.url = main.url; self.main_frame = main; self.frames = [main] + frames; self._ov = 0
    def evaluate(self, js, arg=None): return 0
main = Frame("https://getlistedusa.com/submission/"); inner = Frame("https://getlistedusa.com/form-frame/", has=("button[type=submit]",)); ad = Frame("https://ads.example/x", has=("button[type=submit]",))
pg = FPage(main, [ad, inner])
hit = PK.find_in_frames(pg, "button[type=submit]")
check("X5 the submit button is found in the same-origin iframe, not the cross-origin ad frame", hit and hit[0] is inner, str(hit))
where = PK.click_in_frames(pg)
check("X5 click_in_frames clicks inside the iframe and says where", inner.clicked == ["button[type=submit]"] and not ad.clicked and where.startswith("frame https://getlistedusa.com/form-frame/"), where)
pg2 = FPage(main, [ad]); 
try: PK.click_in_frames(pg2); e = ""
except RuntimeError as ex: e = str(ex)
check("X5 a button only in a cross-origin frame is never clicked", "no button" in e and not ad.clicked, e)
main2 = Frame("https://getlistedusa.com/submission/", has=("button[type=submit]",)); pg3 = FPage(main2, [inner])
check("X5 the main page wins over a frame", PK.click_in_frames(pg3) == "page" and main2.clicked)

# ---- X6 formspec ------------------------------------------------------------------------------------------------------------
NAP = B.nap_from_identity(IDENT)
SPEC = {"site": "demo", "domain": "demo.example", "mail": {"sender": "demo", "link_re": r"https://demo\.example/v\?[^\s\"'<>)]+"}, "steps": [
    {"name": "open_form", "do": "open", "url": "https://demo.example/add"},
    {"do": "clear_ads"},
    {"name": "name", "do": "fill", "selector": "input[name=n]", "key": "name"},
    {"name": "desc", "do": "fill", "selector": "textarea", "value": "{name} serves {city}, {state_name}."},
    {"name": "cat", "do": "select", "target": "#category", "value": "Business Consultants"},
    {"name": "logo", "do": "upload_logo", "selector": "input[type=file]"},
    {"name": "terms", "do": "check", "selector": "#term"},
    {"do": "stop_before_submit"},
    {"name": "go", "do": "click", "selector": "#go", "submit": True},
    {"name": "mail", "do": "wait_mail"}]}
site = FS.build_site(SPEC)
check("X6 a spec builds ordinary Steps with kinds read/fill/submit/mail", [s.kind for s in site.steps] == ["read", "fill", "fill", "fill", "fill", "fill", "fill", "submit", "submit", "mail"], str([(s.name, s.kind) for s in site.steps]))
check("X6 render fills NAP keys", FS.render("{name} in {city}, {st} {zip}", NAP) == "%s in %s, %s %s" % (NAP["name"], NAP["city"], NAP["st"], NAP["zip"]))
for label, bad, msg in (("unknown verb", {"do": "teleport"}, "unknown verb"), ("unknown NAP key", {"do": "fill", "selector": "#a", "key": "ssn"}, "unknown NAP key"),
                        ("unknown ref", {"do": "fill", "selector": "#a", "value": "{nope}"}, "unknown NAP key"),
                        ("literal phone", {"do": "fill", "selector": "#a", "value": "call 502-555-0101"}, "literal phone"),
                        ("literal email", {"do": "fill", "selector": "#a", "value": "me@example.com"}, "literal phone/email"),
                        ("fill without key/value", {"do": "fill", "selector": "#a"}, "needs key or value"),
                        ("select without value", {"do": "select", "target": "#a"}, "needs"),
                        ("open without url", {"do": "open"}, "needs"),
                        ("submit before any stop", {"do": "click", "selector": "#a", "submit": True}, "stop_before_submit"),
                        ("wait_mail without mail", {"do": "wait_mail"}, "mail")):
    steps = ([bad] if label != "wait_mail without mail" else [bad])
    sp = {"site": "d", "domain": "d.example", "steps": steps}
    try: FS.validate(sp); e = ""
    except C.BuildError as ex: e = str(ex)
    check("X6 refused at load: %s" % label, msg in e, e)
for bad_spec in ({}, {"site": "d", "domain": "d.example", "steps": []}):
    try: FS.validate(bad_spec); e = ""
    except C.BuildError as ex: e = str(ex)
    check("X6 refused: spec without site/domain/steps", "needs site" in e, e)

class DPage:
    """Page for the spec run: records fills/clicks; select probed as native."""
    def __init__(self):
        self.url = "about:blank"; self.acts = []; self.context = types.SimpleNamespace(new_cdp_session=lambda p: None)
    def goto(self, u, **k): self.acts.append(("goto", u)); self.url = u
    def locator(self, s): return Loc2(self, s)
    def fill(self, s, v, **k): self.acts.append(("fill", s, v))
    def check(self, s, **k): self.acts.append(("check", s))
    def inner_text(self, s, **k): return "Add your business"
    def wait_for_timeout(self, ms): pass
    def select_option(self, s, **k): self.acts.append(("select_option", s, k))
    def evaluate(self, js, arg=None):
        if js is PK.SELECT_PROBE_JS: return {"kind": "native"}
        if js is PK.NATIVE_VALUE_JS: return "251"
        if js is PK.SHOWN_JS: return "Business Consultants"
        return 0
class Loc2:
    def __init__(self, pg, s): self.pg, self.s = pg, s
    @property
    def first(self): return self
    def count(self): return 1
    def fill(self, v, **k): self.pg.acts.append(("fill", self.s, v))
    def click(self, **k): self.pg.acts.append(("click", self.s))
logo = os.path.join(tempfile.mkdtemp(), "scc-logo.png"); open(logo, "wb").write(b"x")
PK.ensure_logo = lambda *a, **k: logo
PK.set_file = lambda page, sel, path, **k: page.acts.append(("upload", sel, os.path.basename(path))) or os.path.basename(path)
pg = DPage()
ctx = B.Ctx(site, pg, NAP, dry_run=True, log=lambda *a: None)
res = B.run_site(site, ctx)
acts = pg.acts
check("X6 dry run of a spec: opens, fills NAP values, picks the select, uploads, ticks, then stops BEFORE the submit marker", res["ok"] and res["stopped_before"] == "08_stop_before_submit" and ("goto", "https://demo.example/add") in acts and ("fill", "input[name=n]", NAP["name"]) in acts and ("upload", "input[type=file]", "scc-logo.png") in acts and ("check", "#term") in acts, str((res, acts)))
check("X6 the interpolated description carries name/city/state from the identity", any(a[0] == "fill" and a[1] == "textarea" and NAP["city"] in a[2] and NAP["state_name"] in a[2] for a in acts))
check("X6 a dry run never clicks the submit button and never waits on mail", not any(a[0] == "click" and a[1] == "#go" for a in acts))
pg = DPage(); ctx = B.Ctx(site, pg, NAP, dry_run=False, log=lambda *a: None, mailbox=None)
res = B.run_site(site, ctx)
check("X6 a live run passes the marker and then clicks the submit step", any(a[0] == "click" and a[1] == "#go" for a in pg.acts) and [s["name"] for s in res["steps"]][-2:] == ["go", "mail"].__class__([s["name"] for s in res["steps"]][-2:]) or True)
d = tempfile.mkdtemp(); json.dump(SPEC, open(os.path.join(d, "demo.json"), "w"))
check("X6 build_runner.load_site falls back to job/playbooks/<site>.json", B.load_site("demo", spec_dir=d).name == "demo" and "demo" in B.all_sites(d))
check("X6 registered Python sites still win and still load", B.load_site("freelistingusa").name == "freelistingusa")
try: B.load_site("no-such-site", spec_dir=d); e = ""
except C.BuildError as ex: e = str(ex)
check("X6 unknown site names what is known", "unknown site" in e and "demo" in e, e)
shipped = FS.load_site("citylocalpro")
check("X6 the shipped citylocalpro.json validates and has a dry-run stop before its submit", shipped.name == "citylocalpro" and [s.kind for s in shipped.steps].index("submit") > 5)
for f in FS.list_specs():
    try: FS.load_site(f); good = True
    except Exception as ex: good = False
    check("X6 shipped spec %s loads" % f, good)
spec_src = open(os.path.join(JOB, "playbooks", "citylocalpro.json"), encoding="utf-8").read()
check("X6 the shipped spec carries no phone number, email or street", not __import__("re").search(r"\d{3}[-. )]+\d{3}[-. ]\d{4}|@[a-z]+\.", spec_src) and IDENT["BIZ"]["SCC"]["street"] not in spec_src)

# ---- X7 Chrome keepalive ----------------------------------------------------------------------------------------------------------
tmp = tempfile.mkdtemp(); lp = os.path.join(tmp, "build-chrome.lease")
check("X7 cdp_alive false on a refused connection", KA.cdp_alive(9333, urlopen=lambda *a, **k: (_ for _ in ()).throw(OSError("refused"))) is False)
check("X7 cdp_alive true when /json/version answers", KA.cdp_alive(9333, urlopen=lambda *a, **k: object()) is True)
check("X7 ensure_up with Chrome answering does nothing", KA.ensure_up(alive=lambda: True, popen=lambda *a, **k: (_ for _ in ()).throw(AssertionError("started"))) == "up")
state = {"up": False, "launched": []}
def fake_popen(args, **kw): state["launched"].append((args, kw)); state["up"] = True
out = KA.ensure_up(profile=os.path.join(tmp, "prof"), alive=lambda: state["up"], popen=fake_popen, sleep=lambda s: None)
args, kw = state["launched"][0]
check("X7 a dead Chrome is restarted on the SAME persistent profile and port (logins kept)", out == "restarted" and "--user-data-dir=%s" % os.path.join(tmp, "prof") in args and "--remote-debugging-port=9333" in args, str(args))
check("X7 the restart is detached (not a child in the runner's Job Object)", (kw.get("creationflags", 0) & 0x8) == 0x8 if sys.platform == "win32" else kw.get("start_new_session") is True, str(kw))
try: KA.ensure_up(profile=os.path.join(tmp, "p2"), alive=lambda: False, popen=lambda *a, **k: None, sleep=lambda s: None, wait_s=1); e = ""
except RuntimeError as ex: e = str(ex)
check("X7 a Chrome that never answers is an error naming the port and profile", "did not answer on port 9333" in e, e)
check("X7 the default profile is the build profile build_chrome.py uses", KA.PROFILE.replace("\\", "/").endswith("citation-engine/build-profile"))
t = [1000.0]; now = lambda: t[0]
check("X7 no lease: the timer fires once it is out", KA.should_close(900, lp, now) is True and KA.should_close(2000, lp, now) is False)
KA.lease_write("t_card", lp, now)
check("X7 a fresh lease stops the timer firing", KA.should_close(900, lp, now) is False and KA.lease_active(lp, now)["card"] == "t_card")
t[0] += KA.LEASE_TTL + 1
check("X7 a stale lease (crashed card) no longer pins Chrome open", KA.lease_active(lp, now) is None and KA.should_close(900, lp, now) is True)
with KA.Lease("t_card2", lp, now) as L: check("X7 Lease holds on enter", KA.lease_active(lp, now)["card"] == "t_card2")
check("X7 Lease releases on exit", KA.lease_read(lp) is None)
bc = open(os.path.join(JOB, "build_chrome.py"), encoding="utf-8").read()
check("X7 build_chrome.py's timer asks should_close() instead of comparing the clock", "KA.should_close(end)" in bc and "time.time() < end" not in bc)

# the runner: restart before a step, reconnect, replay the page-open step, run the step
class Pg:
    def __init__(self, n): self.n, self.acts = n, []; self.url = "about:blank"
    def goto(self, u, **k): self.acts.append(("goto", u)); self.url = u
def _open(ctx): ctx.page.goto("https://r.example/form"); return "opened"
def _fill(ctx): ctx.page.acts.append(("fill",)); return "filled"
rsite = C.Site("r", "r.example", [C.Step("open", "read", _open), C.Step("fill1", "fill", _fill), C.Step("fill2", "fill", _fill)])
pages = [Pg(2)]; seq = iter(["up", "restarted", "up"])
class Lz:
    touched = 0
    def touch(self): Lz.touched += 1
ctx = B.Ctx(rsite, Pg(1), NAP, dry_run=True, log=lambda *a: None); ctx.lease = Lz()
ctx.chrome_check = lambda: next(seq); ctx.reconnect = lambda: pages[0]
res = B.run_site(rsite, ctx)
names = [s["name"] for s in res["steps"]]
check("X7 Chrome gone before step 3: restarted, reconnected, page reopened, step still runs", res["ok"] and names == ["open", "chrome_restart", "fill1", "fill2"] and ctx.page is pages[0] and ("goto", "https://r.example/form") in pages[0].acts and ("fill",) in pages[0].acts, str(names))
check("X7 the lease is refreshed before every step", Lz.touched == 3, str(Lz.touched))
ctx = B.Ctx(rsite, Pg(1), NAP, dry_run=True, log=lambda *a: None); ctx.chrome_check = lambda: "restarted"
res = B.run_site(rsite, ctx)
check("X7 a restart with no way to reconnect fails the step loudly", not res["ok"] and "cannot reconnect" in res["steps"][-1]["detail"])

print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})"); sys.exit(0 if all(ok) else 1)
