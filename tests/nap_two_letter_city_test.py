"""t_d64aefb4 (PR #105 round 5): the under-street state strip drops only a TRAILING state / zip, never a leading 2-letter city word (St, Mt, El, La, Le, De).
Offline: no network, no prod env. Set NAP_OLD_STRIP=1 to run the mutation (the old whole-pattern (?i) strip is swapped back in; St./El cases must fail)."""
import json, os, re, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import recheck as R

def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net

if os.environ.get("NAP_OLD_STRIP") == "1":
    _sn = "|".join(sorted(R.US_STATES, key=len, reverse=True))
    R.strip_locality_tail = lambda l: re.sub(r"(?i)\b(" + _sn + r")\b|\b[A-Z]{2}\b|\d{5}(-\d{4})?", " ", l.split(",")[0] if "," in l else l)

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

NAME = "Alder Care Services"; P = "(502) 555-0101"; S = "100 Example Dr"

def LD(city, st, z):
    return '<script type="application/ld+json">' + json.dumps({"@type": "LocalBusiness", "name": NAME, "address": {"@type": "PostalAddress", "streetAddress": S, "addressLocality": city, "addressRegion": st, "postalCode": z}}) + "</script>"
def tx(*lines): return "\n".join([NAME, S, *lines, P])
def canon(city, st, z, comma=True): return {"name": NAME, "address": "100 Example Drive, %s%s %s %s" % (city, "," if comma else "", st, z), "phone": P}
def v(text, c, h): return R.compare(text, c, h)["verdict"]

CITIES = [("St. Louis", "MO", "63101"), ("Saint Louis", "MO", "63101"), ("Mt. Vernon", "IL", "62864"), ("El Paso", "TX", "79901"),
          ("La Crosse", "WI", "54601"), ("Le Mars", "IA", "51031"), ("De Pere", "WI", "54115")]
for city, st, z in CITIES:
    for comma in (True, False):
        c = canon(city, st, z, comma); h = LD(city, st, z); tag = "%s canon-comma=%s" % (city, comma)
        for vis in ("%s, %s" % (city, st), "%s %s %s" % (city, st, z), "%s, %s" % (city, st.lower()), "%s, %s %s" % (city, st, z), "%s %s" % (city, st)):
            check("match: %s visible '%s' + good LD" % (tag, vis), v(tx(vis), c, h) == "match")

# state-word cities (full state name inside the city), lower-case state
for city, st, z in (("Kansas City", "MO", "64101"), ("Virginia Beach", "VA", "23451"), ("Texas City", "TX", "77590"), ("Oklahoma City", "OK", "73101")):
    c = canon(city, st, z); h = LD(city, st, z)
    for vis in ("%s, %s" % (city, st.lower()), "%s %s %s" % (city, st.lower(), z), "%s, %s %s" % (city, st.lower(), z), "%s, %s" % (city, st)):
        check("match: %s visible '%s' + good LD" % (city, vis), v(tx(vis), c, h) == "match")
check("mismatch: canonical Kansas City, visible 'Kansas, MO'", v(tx("Kansas, MO"), canon("Kansas City", "MO", "64101"), LD("Kansas City", "MO", "64101")) == "mismatch")
check("mismatch: canonical Texas City, visible 'Texas, TX'", v(tx("Texas, TX"), canon("Texas City", "TX", "77590"), LD("Texas City", "TX", "77590")) == "mismatch")

# St. / Saint are one city either way round
check("match: canonical 'Saint Louis', visible 'St. Louis, MO'", v(tx("St. Louis, MO"), canon("Saint Louis", "MO", "63101"), LD("Saint Louis", "MO", "63101")) == "match")
check("match: canonical 'St. Louis', visible 'Saint Louis, MO'", v(tx("Saint Louis, MO"), canon("St. Louis", "MO", "63101"), LD("St. Louis", "MO", "63101")) == "match")

# wrong city, same state -> mismatch
c = canon("El Paso", "TX", "79901"); h = LD("El Paso", "TX", "79901")
for vis in ("Dallas, TX", "Dallas TX 79901", "Dallas, tx"):
    check("mismatch: canonical El Paso, visible '%s'" % vis, v(tx(vis), c, h) == "mismatch")
c = canon("St. Louis", "MO", "63101"); h = LD("St. Louis", "MO", "63101")
for vis in ("Kansas City, MO", "St. Charles, MO", "Mt. Vernon, MO"):
    check("mismatch: canonical St. Louis, visible '%s'" % vis, v(tx(vis), c, h) == "mismatch")
# wrong state -> mismatch
for vis in ("St. Louis, IL", "St. Louis IL 63101", "St. Louis, il"):
    check("mismatch: canonical St. Louis MO, visible '%s'" % vis, v(tx(vis), c, h) == "mismatch")
check("mismatch: wrong zip 'St. Louis, MO 99999'", v(tx("St. Louis, MO 99999"), c, h) == "mismatch")

# a same-name JSON-LD block with no street next to a good one disagrees -> never a match (QA r4 partial-block case)
_part = '<script type="application/ld+json">' + json.dumps({"@type": "LocalBusiness", "name": NAME, "address": {"@type": "PostalAddress", "addressLocality": "Fort Worth", "addressRegion": "IN"}}) + "</script>"
_FW = {"name": NAME, "address": "100 Example Drive, Fort Wayne, IN 46802", "phone": P}
check("not match: street-less same-name LD + good LD", v(tx(), _FW, _part + LD("Fort Wayne", "IN", "46802")) != "match" and v("\n".join([NAME, S, P]), _FW, _part + LD("Fort Wayne", "IN", "46802")) != "match")

# helper unit cases
T = R.strip_locality_tail
for line, want in (("St. Louis, MO", "St. Louis"), ("Mt. Vernon, IL 62864", "Mt. Vernon"), ("El Paso TX 79901", "El Paso"), ("La Crosse, wi", "La Crosse"),
                   ("Le Mars IA", "Le Mars"), ("De Pere, Wisconsin", "De Pere"), ("Fort Wayne OH", "Fort Wayne"), ("Oklahoma City, OK", "Oklahoma City"),
                   ("KY 40000", ""), ("Ohio", ""), ("St. Louis", "St. Louis"), ("Kansas City, mo", "Kansas City"), ("Virginia Beach, va", "Virginia Beach"),
                   ("Texas City tx 77590", "Texas City"), ("Kansas City", "Kansas City"), ("Kansas, MO", "Kansas")):
    check("strip_locality_tail(%r) == %r" % (line, want), T(line) == want, T(line))

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
