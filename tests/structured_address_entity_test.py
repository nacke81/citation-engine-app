"""t_ff6ed622: structured_address picks the business's own PostalAddress, never the directory's sitewide Organization block (the storeboard false mismatch).
Fixture shape: anonymized storeboard listing page, test identity (tests/test_identity.json). Run: python tests/structured_address_entity_test.py. No network."""
import os, sys, json, tempfile, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ["CE_RUNS"] = tempfile.mkdtemp(prefix="ce-runs-")
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import recheck as R
import claim

def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

NAME = "Alder Care Consulting & Solutions"
CANON = {"name": NAME, "address": "100 Example, Exampleton, KY 40000", "phone": "(502) 555-0101"}
PAD = "<p>Lorem ipsum dolor sit amet.</p>" * 12

def ld(o): return '<script type="application/ld+json">%s</script>' % json.dumps(o)
def pa(street, city, region, zip_): return {"@type": "PostalAddress", "streetAddress": street, "addressLocality": city, "addressRegion": region, "postalCode": zip_}
# The directory's own sitewide block (anonymized: Florida corporate address stands in for Storeboard's).
SITE_ORG = ld({"@context": "https://schema.org", "@type": "Organization", "name": "Directory Example", "url": "https://directory.example/", "address": pa("500 Federal Hwy Unit 1", "Hallandale Beach", "FL", "33009")})
def entity(addr, typ="LocalBusiness", name=NAME, extra=None):
    d = {"@context": "https://schema.org", "@type": typ, "name": name, "telephone": "(502) 555-0101", "address": addr}
    d.update(extra or {})
    return ld(d)
def page(*blocks):
    # the listing text carries the name and phone only: the street lives in the markup (so structured_address is the address source)
    return "<html><head>" + "".join(blocks) + "</head><body><h1>%s</h1><p>(502) 555-0101</p>%s</body></html>" % (NAME.replace("&", "&amp;"), PAD)
def verdict(h, canon=CANON):
    return R.compare(claim.html_to_text(h), canon, h)

RIGHT = pa("100 Example", "Exampleton", "Kentucky", "40000")
WRONG = pa("100 Example", "Otherville", "Kentucky", "40000")

# Site Organization first (the order that made the 11/03 audit read Florida), SCC entity second
h = page(SITE_ORG, entity(RIGHT))
check("S1 structured_address picks the business entity, not the site Organization", R.structured_address(h, NAME) == {"street": "100 Example", "city": "Exampleton", "state": "Kentucky", "zip": "40000"}, R.structured_address(h, NAME))
v = verdict(h)
check("S2 SCC entity right + site Organization in FL -> match", v["verdict"] == "match", v)
check("S3 same with the entity first", verdict(page(entity(RIGHT), SITE_ORG))["verdict"] == "match")
v = verdict(page(SITE_ORG, entity(WRONG)))
check("S4 SCC entity in a wrong city (site Organization in FL) -> mismatch", v["verdict"] == "mismatch", v)
v = verdict(page(SITE_ORG, entity(pa("102 Example", "Exampleton", "KY", "40000"))))
check("S5 wrong street inside the business entity -> mismatch", v["verdict"] == "mismatch", v)
# entity matched by name even when typed Organization (the business's own entity)
check("S6 name match wins over type (Organization named as the business)", R.structured_address(page(SITE_ORG, entity(RIGHT, typ="Organization")), NAME)["city"] == "Exampleton")
# nested: LocalBusiness subtype, name differs slightly in punctuation / suffix
check("S7 name normalized (And / LLC / punctuation)", R.structured_address(page(SITE_ORG, entity(RIGHT, typ="ProfessionalService", name=NAME.replace("&", "and") + ", LLC")), NAME)["city"] == "Exampleton")
# LocalBusiness subtype with a different name (a listing title variant) beats Organization
check("S8 LocalBusiness subtype beats Organization when no name matches", R.structured_address(page(SITE_ORG, entity(RIGHT, typ="ProfessionalService", name="Alder Care")), NAME)["city"] == "Exampleton")
# only the directory's Organization on the page: never used
check("S9 site Organization alone -> None, never its address", R.structured_address(page(SITE_ORG), NAME) is None)
v = verdict(page(SITE_ORG))
check("S10 site Organization alone is not a mismatch (no address read -> nap-incomplete)", v["verdict"] == "nap-incomplete", v)
# text block carries the canonical street + city: the Organization block never overrides it
txt = "<html><head>%s</head><body><h1>%s</h1><p>100 Example</p><p>Exampleton, KY 40000</p><p>(502) 555-0101</p>%s</body></html>" % (SITE_ORG, NAME.replace("&", "&amp;"), PAD)
v = verdict(txt)
check("S11 text block NAP + site Organization in FL -> match", v["verdict"] == "match", v)
# WebSite / Organization list types
check("S12 @type list of org-like types is not a business", R.structured_address(page(entity(pa("1 X", "Y", "FL", "33009"), typ=["Organization", "WebSite"], name="Directory Example")), NAME) is None)
# no business_name: legacy first-block behavior (nextdoor shape, N5 in proof_gate_test)
check("S13 no business name -> first block, as before", R.structured_address(page(SITE_ORG, entity(RIGHT)))["city"] == "Hallandale Beach")

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
