"""NAP reader: a visible street must not suppress the same entity's JSON-LD city/state/ZIP (t_69102cc9). Run: python tests/nap_structured_locality_test.py (CI). No network.
The page is the live Nextdoor listing shape saved 2026-11-13 (tests/fixtures/nextdoor-live-shape-20261113.html, sanitized to the test identity): the text shows the
street, phone and site but no city / state / ZIP; the page's own JSON-LD LocalBusiness carries the full PostalAddress."""
import os, re, sys, tempfile, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ["CE_RUNS"] = tempfile.mkdtemp(prefix="ce-runs-")
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import recheck as R
import proof as PR
import sitegate as SG
import claim

def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

HTML = open(os.path.join(HERE, "fixtures", "nextdoor-live-shape-20261113.html"), encoding="utf-8").read()
CANON = {"name": "Alder Care Consulting & Solutions", "address": "100 Example Dr, Exampleton, KY 40000", "phone": "(502) 555-0101"}
TEXT = claim.html_to_text(HTML)
LD_RE = re.compile(r'(?is)(<script[^>]*ld\+json[^>]*>)(.*?)(</script>)')

def ld(h, a, b):   # edit only inside the JSON-LD scripts
    return LD_RE.sub(lambda m: m.group(1) + m.group(2).replace(a, b) + m.group(3), h)
def vis(h, a, b):   # edit only outside the JSON-LD scripts (what a visitor reads)
    parts, last, out = [], 0, []
    for m in LD_RE.finditer(h):
        out.append(h[last:m.start()].replace(a, b)); out.append(m.group(0)); last = m.end()
    out.append(h[last:].replace(a, b)); return "".join(out)
def cmp_(html, canon=CANON, text=None): return R.compare(text if text is not None else claim.html_to_text(html), canon, html)
def ldonly(addr_json, name="Alder Care Consulting &amp; Solutions", typ="LocalBusiness"):
    return '<script type="application/ld+json">{"@context":"https://schema.org","@type":"%s","name":"%s","address":%s}</script>' % (typ, name.replace("&amp;", "&"), addr_json)
FULL_LD = '{"@type":"PostalAddress","streetAddress":"100 Example Dr","addressLocality":"Exampleton","addressRegion":"KY","postalCode":"40000"}'
PAD = " Lorem ipsum dolor sit amet." * 12
def street_text(*extra): return "Home\nAlder Care Consulting & Solutions\nAlder Care Consulting & Solutions\n100 Example Dr\n" + "".join(x + "\n" for x in extra) + "(502) 555-0101\n" + PAD

# the saved page shape really is street-only in the text (the old bug's input)
check("P0 fixture text shows the street and no city/ZIP line under it", "100 Example Dr" in TEXT and not re.search(r"100 Example Dr\s*\n?\s*Exampleton", TEXT), TEXT[:200])
check("P0 fixture JSON-LD carries the full PostalAddress of the same entity", R.structured_address(HTML, CANON["name"], same_entity=True) == {"street": "100 Example Dr", "city": "Exampleton", "state": "KY", "zip": "40000"}, R.structured_address(HTML, CANON["name"], same_entity=True))

# C1 the real captured page matches, with the structured locality in the NAP
c = cmp_(HTML)
check("C1 real captured page: match", c["verdict"] == "match" and not c["wrong"] and not c["gaps"], c)
check("C1 NAP quotes street + structured city/state/ZIP", "100 Example Dr, Exampleton, KY 40000" in c["nap"], c["nap"])

# C2 same street-only text without the markup stays nap-incomplete
c = R.compare(TEXT, CANON)
check("C2 same text, no HTML: nap-incomplete address", c["verdict"] == "nap-incomplete" and c["gaps"] == ["address"], c)
check("C2 same text, html with no JSON-LD address: nap-incomplete", cmp_("<html><body>x</body></html>", text=TEXT)["verdict"] == "nap-incomplete")

# C3 wrong structured city / state / ZIP -> mismatch (never match, never incomplete)
for label, a, b, fld in (("city", '"addressLocality":"Exampleton"', '"addressLocality":"Otherville"', "city"), ("state", '"addressRegion":"KY"', '"addressRegion":"TN"', "state"),
                         ("zip", '"postalCode":"40000"', '"postalCode":"99999"', "zip")):
    c = cmp_(ld(HTML, a, b))
    check("C3 wrong structured %s -> mismatch on %s" % (label, fld), c["verdict"] == "mismatch" and [f for f, _v in c["wrong"]] == [fld], c)
check("C3 structured state spelled out (Kentucky) still matches", cmp_(ld(HTML, '"addressRegion":"KY"', '"addressRegion":"Kentucky"'))["verdict"] == "match")
check("C3 structured part missing (no ZIP) -> nap-incomplete", cmp_(ld(HTML, '"postalCode":"40000",', ""))["verdict"] == "nap-incomplete", cmp_(ld(HTML, '"postalCode":"40000",', "")))

# C4 wrong visible street + correct JSON-LD -> mismatch (JSON-LD never overrides what the page shows)
h4 = vis(HTML, "100 Example Dr", "102 Example Dr")
c = cmp_(h4)
check("C4 visible wrong street, correct JSON-LD -> mismatch address", c["verdict"] == "mismatch" and c["wrong"] and c["wrong"][0][0] == "address", c)
check("C4 visible wrong street never matches via JSON-LD street", "match" != cmp_(h4)["verdict"])

# C5 visible locality fragments that are wrong + correct JSON-LD -> mismatch
for label, extra, fld in (("city", "Otherville, KY 40000", "city"), ("state", "TN 40000", "state"), ("zip", "KY 99999", "zip"), ("zip alone", "99999", "zip")):
    c = R.compare(street_text(extra), CANON, ldonly(FULL_LD))
    check("C5 visible wrong %s (%s) + correct JSON-LD -> mismatch %s" % (label, extra, fld), c["verdict"] == "mismatch" and (fld in [f for f, _v in c["wrong"]] or ("zip" in fld and "99999" in str(c["wrong"]))), c)   # a ZIP on the street line is reported as the address (existing wording)
c = R.compare(street_text("KY 40000"), CANON, ldonly(FULL_LD))
check("C5 visible state+ZIP that agree, city from the same entity's JSON-LD -> match", c["verdict"] == "match", c)

# C6 unrelated entities cannot supply the locality
for label, h in (("directory HQ Organization, other name", ldonly(FULL_LD, name="Example Directory Inc", typ="Organization")),
                 ("other LocalBusiness, other name", ldonly(FULL_LD, name="Other Care LLC")),
                 ("nameless LocalBusiness", '<script type="application/ld+json">{"@type":"LocalBusiness","address":%s}</script>' % FULL_LD),
                 ("same-name entity with a different street", ldonly(FULL_LD.replace("100 Example Dr", "7 Corporate Way"))),
                 ("page-level Organization HQ with the canonical street", ldonly(FULL_LD, name="Example Directory Inc", typ="WebSite"))):
    c = R.compare(street_text(), CANON, h)
    check("C6 %s: stays nap-incomplete" % label, c["verdict"] == "nap-incomplete" and c["gaps"] == ["address"], c)
c = R.compare(street_text(), CANON, ldonly(FULL_LD.replace("Exampleton", "Otherville"), name="Other Care LLC"))
check("C6 another entity's WRONG locality is not read at all (no mismatch from a stranger)", c["verdict"] == "nap-incomplete", c)
check("C6 selector fields alone (no JSON-LD) never supplement", R.compare(street_text(), CANON, '<div class="city-selector">Exampleton</div><div class="state-selector">KY</div><div class="zip-code-selector">40000</div>')["verdict"] == "nap-incomplete")

# C7 a visible full locality is read from the text exactly as before (no structured data needed)
c = R.compare(street_text("Exampleton, KY 40000"), CANON)
check("C7 visible City, ST ZIP still matches without HTML", c["verdict"] == "match", c)
check("C7 visible wrong city still mismatches without HTML", R.compare(street_text("Otherville, KY 40000"), CANON)["verdict"] == "mismatch")
check("C7 default structured_address ignores same_entity=False behaviour (first LocalBusiness fallback kept)", R.structured_address(ldonly(FULL_LD, name="Other Care LLC"), CANON["name"]) is not None)

# C8 ONE comparator: proof's re-read goes through recheck.read_listing -> compare with the page HTML
d = tempfile.mkdtemp()
guard = SG.SiteGuard(path=os.path.join(d, "g.json"), logs=os.path.join(d, "logs"), gap=0)
def plain(u, *a, **k): return R.Page(200, u, TEXT, html=HTML)
def chrome(u, *a, **k): raise AssertionError("chrome must not be needed")
v = PR.recheck_verdict("https://a.example/pages/x/", CANON, guard=guard, plain=plain, chrome=chrome)
check("C8 proof re-read of the real page: match, same NAP as recheck", v["verdict"] == "match" and v["nap"] == cmp_(HTML)["nap"], v)
v = PR.recheck_verdict("https://a.example/pages/x/", CANON, guard=guard, plain=lambda u, *a, **k: R.Page(200, u, TEXT, html=None), chrome=lambda u, *a, **k: R.Page(200, u, TEXT, html=None))
check("C8 proof re-read without markup: nap-incomplete", v["verdict"] == "nap-incomplete", v)
src = open(os.path.join(HERE, "..", "job", "recheck.py"), encoding="utf-8").read()
check("C8 no Directory / client names in the supplement path", not re.search(r"(?i)nextdoor|senior care", src[src.index("t_69102cc9: the text shows"):src.index("street_txt = got[0] if got else None")]))

# C9 mutation: remove the supplementation (structured_address same_entity returns nothing) and the real-page regression must fail
orig = R.structured_address
R.structured_address = lambda html_, name=None, same_entity=False: None if same_entity else orig(html_, name, same_entity)
try: mut = cmp_(HTML)["verdict"]
finally: R.structured_address = orig
check("C9 mutation (supplementation removed): the real-page regression flips to nap-incomplete", mut == "nap-incomplete", mut)
check("C9 restored: match again", cmp_(HTML)["verdict"] == "match")

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
