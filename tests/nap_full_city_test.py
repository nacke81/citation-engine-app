"""t_0227a3ce (PR #105 round 4): the WHOLE city is compared (Fort Wayne != Fort Worth), a visible state is read in any case, and same-name JSON-LD blocks that disagree
are never a match. One city comparator serves the supplement and the structured-address path. Offline: no network, no prod env."""
import json, os, re, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import recheck as R
import claim

def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

NAME = "Alder Care Services"; P = "(502) 555-0101"; S = "100 Example Dr"
FW = {"name": NAME, "address": "100 Example Drive, Fort Wayne, IN 46802", "phone": P}
FW2 = {"name": NAME, "address": "100 Example Drive, Fort Wayne IN 46802", "phone": P}   # no comma before the state
MV = {"name": NAME, "address": "100 Example Drive, Exampleton KY 40000", "phone": P}

def LD(street, city, st, z, name=NAME, typ="LocalBusiness"):
    return '<script type="application/ld+json">' + json.dumps({"@type": typ, "name": name, "address": {"@type": "PostalAddress", "streetAddress": street, "addressLocality": city, "addressRegion": st, "postalCode": z}}) + "</script>"
def GRAPH(city):
    return '<script type="application/ld+json">' + json.dumps({"@graph": [{"@type": "Organization", "name": "Directory Inc"}, {"@type": "LocalBusiness", "name": NAME, "address": {"@type": "PostalAddress", "streetAddress": S, "addressLocality": city, "addressRegion": "IN", "postalCode": "46802"}}]}) + "</script>"
def tx(*lines, phone=P, name=NAME): return "\n".join([name, *lines, phone])
def v(text, canon, html_): return R.compare(text, canon, html_)["verdict"]

GOOD = LD(S, "Fort Wayne", "IN", "46802")
for canon_label, C in (("3-part canonical", FW), ("2-part canonical", FW2)):
    L = canon_label
    check("D1 %s: control, good LD -> match" % L, v(tx(S), C, GOOD) == "match")
    check("D2 %s: LD city Fort Worth -> mismatch" % L, v(tx(S), C, LD(S, "Fort Worth", "IN", "46802")) == "mismatch")
    check("D2 %s: LD city Fort Smith -> mismatch" % L, v(tx(S), C, LD(S, "Fort Smith", "IN", "46802")) == "mismatch")
    check("D3 %s: visible bare 'Fort Worth' + good LD -> not match" % L, v(tx(S, "Fort Worth"), C, GOOD) != "match")
    check("D3 %s: visible 'Fort Worth, IN' + good LD -> not match" % L, v(tx(S, "Fort Worth, IN"), C, GOOD) != "match")
    check("D3 %s: visible same-line ', Fort Worth' + good LD -> not match" % L, v(tx(S + ", Fort Worth"), C, GOOD) != "match")
    check("D3 %s: visible same-line ', Fort Worth, IN 46802' + good LD -> not match" % L, v(tx(S + ", Fort Worth, IN 46802"), C, GOOD) != "match")
    check("D4 %s: visible 'Fort Wayne, oh' + good LD -> mismatch" % L, v(tx(S, "Fort Wayne, oh"), C, GOOD) == "mismatch")
    check("D4 %s: visible 'Fort Wayne, Ohio' + good LD -> mismatch" % L, v(tx(S, "Fort Wayne, ohio"), C, GOOD) == "mismatch")
    check("D4 %s: visible 'Fort Wayne, in' + good LD -> match" % L, v(tx(S, "Fort Wayne, in"), C, GOOD) == "match")
    check("D4 %s: visible 'FORT WAYNE, IN' + good LD -> match" % L, v(tx(S, "FORT WAYNE, IN"), C, GOOD) == "match")
    check("D6 %s: @graph-nested LocalBusiness, wrong city -> mismatch" % L, v(tx(S), C, GRAPH("Fort Worth")) == "mismatch")
    check("D6 %s: @graph-nested LocalBusiness, good city -> match" % L, v(tx(S), C, GRAPH("Fort Wayne")) == "match")
    bad_st = LD("500 Other Rd", "Fort Wayne", "IN", "46802")
    wrongcity = LD(S, "Fort Worth", "IN", "46802")
    check("D7 %s: bad-street same-name LD THEN good LD -> not match" % L, v(tx(S), C, bad_st + GOOD) != "match")
    check("D7 %s: good LD THEN bad-street same-name LD -> not match" % L, v(tx(S), C, GOOD + bad_st) != "match")
    check("D7 %s: wrong-city same-street LD THEN good LD -> not match" % L, v(tx(S), C, wrongcity + GOOD) != "match")
    check("D7 %s: good LD THEN wrong-city same-street LD -> not match" % L, v(tx(S), C, GOOD + wrongcity) != "match")
    check("D7 %s: two same-name LD blocks that AGREE -> match" % L, v(tx(S), C, GOOD + GOOD) == "match")
    check("D8 %s: accepted F21: WebSite/Place-typed block with the business name and the correct address -> match (known, accepted)" % L, v(tx(S), C, LD(S, "Fort Wayne", "IN", "46802", typ="Organization")) == "match")
    check("D9 %s: unrelated Organization address still cannot supply it" % L, v(tx(S), C, LD(S, "Fort Wayne", "IN", "46802", name="Directory Inc", typ="Organization")) == "nap-incomplete")

# no-street structured path shares the comparator (no visible street at all)
check("D1b structured-address path (no visible street): LD Fort Worth -> mismatch", v(tx(), FW, LD(S, "Fort Worth", "IN", "46802")) == "mismatch")
check("D1b structured-address path: LD Fort Wayne -> match", v(tx(), FW, GOOD) == "match")
check("D1b structured-address path: 'Saint' vs 'St.' is one city", v(tx(), {**FW, "address": "100 Example Drive, Saint Louis, MO 63101"}, LD(S, "St. Louis", "MO", "63101")) == "match")

# the real-shape page (sanitized fixture) and the SCC-shaped canonical
HTML = open(os.path.join(HERE, "fixtures", "nextdoor-live-shape-20261113.html"), encoding="utf-8").read()
CANON = {"name": "Alder Care Consulting & Solutions", "address": "100 Example Dr, Exampleton, KY 40000", "phone": "(502) 555-0101"}
TEXT = claim.html_to_text(HTML)
check("D5 real-shape fixture -> match", R.compare(TEXT, CANON, HTML)["verdict"] == "match")
M = lambda *x: tx(*x, name=MV["name"])
check("D5 Exampleton, tn (lowercase wrong state) + good LD -> mismatch", v(tx("100 Example Dr", "Exampleton, tn"), MV, LD("100 Example Dr", "Exampleton", "KY", "40000")) == "mismatch")
check("D5 Exampleton, ky (lowercase right state) + good LD -> match", v(tx("100 Example Dr", "Exampleton, ky"), MV, LD("100 Example Dr", "Exampleton", "KY", "40000")) == "match")
check("D5 Exampleton, TN + good LD -> mismatch", v(tx("100 Example Dr", "Exampleton, TN"), MV, LD("100 Example Dr", "Exampleton", "KY", "40000")) == "mismatch")

# mutation 1: first-token city compare -> the Fort Worth tests must fail
def first_token(shown, want, tail_ok=False):
    a, b = (shown if isinstance(shown, list) else R.ctok(shown)), (want if isinstance(want, list) else R.ctok(want, True))
    return bool(a) and bool(b) and a[:1] == b[:1]
orig_cs, orig_vs = R.city_same, R.vis_state
R.city_same = first_token
try:
    m1 = (v(tx(S), FW, LD(S, "Fort Worth", "IN", "46802")), v(tx(S, "Fort Worth"), FW, GOOD), v(tx(S + ", Fort Worth"), FW, GOOD), v(tx(S), FW, GRAPH("Fort Worth")))
finally: R.city_same = orig_cs
check("M1 mutation (first-token compare): every Fort Worth case turns into a false match", all(x == "match" for x in m1), m1)
check("M1 restored: Fort Worth -> mismatch again", v(tx(S), FW, LD(S, "Fort Worth", "IN", "46802")) == "mismatch")

# mutation 2: upper-case-only visible state -> the lowercase tests must fail
def upper_only(line):
    m = re.search(r"(?<![A-Za-z])([A-Z]{2})\.?(?=\s+\d{5}\b|\s*$)", line)
    return m.group(1) if m else None
R.vis_state = upper_only
try:
    m2 = (v(tx(S, "Fort Wayne, oh"), FW, GOOD), v(tx("100 Example Dr", "Exampleton, tn"), MV, LD("100 Example Dr", "Exampleton", "KY", "40000")))
finally: R.vis_state = orig_vs
check("M2 mutation (case fold removed): the lowercase wrong-state cases turn into false matches", all(x == "match" for x in m2), m2)
check("M2 restored: 'Fort Wayne, oh' -> mismatch again", v(tx(S, "Fort Wayne, oh"), FW, GOOD) == "mismatch")

# mutation 3: same-name blocks no longer cross-checked (first block wins) -> the good-then-bad order is a false match
orig_sa = R.structured_address
def first_wins(html_, name=None, same_entity=False):
    if not same_entity: return orig_sa(html_, name, same_entity)
    m = re.search(r'(?is)<script[^>]*ld\+json[^>]*>.*?</script>', html_)
    return orig_sa(m.group(0), name, True) if m else None
R.structured_address = first_wins
try: m3 = v(tx(S), FW, GOOD + bad_st)
finally: R.structured_address = orig_sa
check("M3 mutation (first same-name block wins): good-then-bad becomes a false match", m3 == "match", m3)
check("M3 restored: good-then-bad -> not match", v(tx(S), FW, GOOD + bad_st) != "match")

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
