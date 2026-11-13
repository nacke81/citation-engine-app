"""NAP reader (t_69102cc9, review rounds 1-2): the state/ZIP check must hold for BOTH canonical spellings, `street, City, ST zip` and `street, City ST zip`, and a visible wrong
locality UNDER the street must never be overridden by JSON-LD. Run: python tests/nap_locality_forms_test.py (CI). No network."""
import os, re, sys, tempfile, urllib.request
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

HTML = open(os.path.join(HERE, "fixtures", "nextdoor-live-shape-20261113.html"), encoding="utf-8").read()
NAME = "Alder Care Consulting & Solutions"
FORMS = {"3-part": "100 Example Dr, Exampleton, KY 40000", "2-part": "100 Example Drive, Exampleton KY 40000"}
LD_RE = re.compile(r'(?is)(<script[^>]*ld\+json[^>]*>)(.*?)(</script>)')
def ld(h, a, b): return LD_RE.sub(lambda m: m.group(1) + m.group(2).replace(a, b) + m.group(3), h)
def ldonly(region="KY", zp="40000", city="Exampleton", street="100 Example Dr"):
    a = '{"@type":"PostalAddress","streetAddress":"%s","addressLocality":"%s","addressRegion":"%s","postalCode":"%s"}' % (street, city, region, zp)
    return '<script type="application/ld+json">{"@type":"LocalBusiness","name":"%s","address":%s}</script>' % (NAME, a)
PAD = " Lorem ipsum dolor sit amet." * 12
def text(*extra): return "Home\n%s\n%s\n100 Example Dr\n" % (NAME, NAME) + "".join(x + "\n" for x in extra) + "(502) 555-0101\n" + PAD
def fields(c): return [f for f, _v in c["wrong"]]

check("H0 canon_state_zip reads both forms", [R.canon_state_zip(a) for a in FORMS.values()] == [("KY", "40000")] * 2 and R.canon_state_zip("100 Example Dr") == (None, None), [R.canon_state_zip(a) for a in FORMS.values()])

for form, addr in FORMS.items():
    CANON = {"name": NAME, "address": addr, "phone": "(502) 555-0101"}
    T = lambda label: "[%s] %s" % (form, label)
    c = R.compare(claim.html_to_text(HTML), CANON, HTML)
    check(T("real-shape page matches"), c["verdict"] == "match" and "KY 40000" in c["nap"], c)
    # C3: wrong structured city/state/zip with the street-only text (supplement path)
    for label, kw, fld in (("city", dict(city="Otherville"), "city"), ("state", dict(region="TN"), "state"), ("zip", dict(zp="99999"), "zip")):
        c = R.compare(text(), CANON, ldonly(**kw))
        check(T("C3 supplement: wrong structured %s -> mismatch" % label), c["verdict"] == "mismatch" and fld in fields(c), c)
    # C5: visible wrong locality on the street's own following line + correct LD
    for label, extra, fld in (("state TN 40000", "TN 40000", "state"), ("zip KY 99999", "KY 99999", "zip"), ("zip alone", "99999", "zip"), ("city, state", "Otherville, KY 40000", "city"),
                              ("next-line wrong ST zip", "TN 40000", "state")):
        c = R.compare(text(extra), CANON, ldonly())
        check(T("C5 visible wrong %s + correct LD -> mismatch" % label), c["verdict"] == "mismatch", c)
    c = R.compare(text("KY 40000"), CANON, ldonly())
    check(T("C5 visible KY 40000 + correct LD -> match"), c["verdict"] == "match", c)
    # round-1 repros: wrong locality on the line(s) under the street
    for label, lines in (("Hopkinsville", ["Hopkinsville"]), ("Hopkinsville, TN", ["Hopkinsville, TN"]), ("Kentucky 99999", ["Kentucky 99999"]), ("Tennessee 40000", ["Tennessee 40000"]),
                         ("city / wrong state", ["Exampleton", "TN 40000"]), ("zip-first wrong", ["99999", "Exampleton", "KY"])):
        c = R.compare(text(*lines), CANON, ldonly())
        check(T("N1 under-street %s + correct LD -> not match" % label), c["verdict"] != "match", c)
    for label, lines in (("Hopkinsville, TN", ["Hopkinsville, TN"]), ("Kentucky 99999", ["Kentucky 99999"]), ("Tennessee 40000", ["Tennessee 40000"]), ("city / wrong state", ["Exampleton", "TN 40000"])):
        c = R.compare(text(*lines), CANON, ldonly())
        check(T("N1 under-street %s + correct LD -> mismatch" % label), c["verdict"] == "mismatch", c)
    for label, lines in (("Exampleton, KY 40000", ["Exampleton, KY 40000"]), ("Exampleton only", ["Exampleton"]), ("Exampleton / KY 40000", ["Exampleton", "KY 40000"])):
        c = R.compare(text(*lines), CANON, ldonly())
        check(T("N1 under-street %s + correct LD -> match" % label), c["verdict"] == "match", c)
    # round 2: zip-before-city under the street ("40000 City[, ST]") - the visible city is checked, never filled from LD
    for label, lines, want in (("40000 Otherville", ["40000 Otherville"], "mismatch"), ("40000 Otherville, KY", ["40000 Otherville, KY"], "mismatch"), ("40000 Exampleton, TN", ["40000 Exampleton, TN"], "mismatch"),
                               ("99999 Exampleton", ["99999 Exampleton"], "mismatch"), ("40000 Exampleton", ["40000 Exampleton"], "match"), ("40000 Exampleton, KY", ["40000 Exampleton, KY"], "match"), ("40000 alone", ["40000"], "match")):
        c = R.compare(text(*lines), CANON, ldonly())
        check(T("Z1 zip-first '%s' + correct LD -> %s" % (label, want)), c["verdict"] == want, c)
    # old structured path: no street in the text, LD carries everything
    nostreet = "Home\n%s\n(502) 555-0101\n" % NAME + PAD
    c = R.compare(nostreet, CANON, ldonly())
    check(T("old path: correct LD -> match"), c["verdict"] == "match", c)
    for label, kw, fld in (("state", dict(region="TN"), "state"), ("zip", dict(zp="99999"), "zip"), ("city", dict(city="Otherville"), "city")):
        c = R.compare(nostreet, CANON, ldonly(**kw))
        check(T("old path: wrong LD %s -> mismatch" % label), c["verdict"] == "mismatch" and fld in fields(c), c)

# canonical with no readable state: unverifiable, never a match
CANON = {"name": NAME, "address": "100 Example Dr, Exampleton", "phone": "(502) 555-0101"}
check("U1 unreadable canonical state: supplement never matches", R.compare(text(), CANON, ldonly())["verdict"] != "match")
check("U1 unreadable canonical state: old path never matches", R.compare("Home\n%s\n(502) 555-0101\n" % NAME + PAD, CANON, ldonly())["verdict"] != "match")

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
