"""NAP reader: a complete 'Full Address' row beats a partial Address Details block (t_59f339e5). Run: python tests/localstar_full_address_test.py (CI). No network.
Fixture tests/fixtures/localstar-scc-20261118.html is the signed-out localstar listing page (saved 2026-11-18), sanitized to the test identity: its Address Details block
shows the street and city only; its Full Address row shows street, city, state and ZIP."""
import os; os.environ["CE_DIRECTORIES_WRITE"] = "0"   # t_be2150cd: never write the prod Directory DB
import os, re, sys, tempfile, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ["CE_RUNS"] = tempfile.mkdtemp(prefix="ce-runs-")
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import os as _fo; _fo.environ["CE_PORTAL_ENV"] = _fo.path.join(_fo.path.dirname(_fo.path.abspath(__file__)), "no-such-portal.env")  # t_2ddc7067: fail closed, never the prod portal
import recheck as R
import claim

def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

HTML = open(os.path.join(HERE, "fixtures", "localstar-scc-20261118.html"), encoding="utf-8").read()
CANON = {"name": "Alder Care Consulting & Solutions", "address": "100 Example Dr, Exampleton, KY 40000", "phone": "(502) 555-0101"}
FULL = "100 Example Dr, Exampleton, KY 40000"
def cmp_(h, canon=CANON): return R.compare(claim.html_to_text(h), canon, h)
def row(h, new): assert FULL in h; return h.replace("<span>%s</span>" % FULL, "<span>%s</span>" % new)   # edit the Full Address row only (the map script keeps its own copy)
def fields(c): return sorted(f for f, _v in c["wrong"])

T = claim.html_to_text(HTML)
check("P0 fixture: the Address Details block is partial (street + city, no state / ZIP)", re.search(r"Address Details\n100 Example Dr\nExampleton\nPhone", T) is not None, T[T.find("Address Details"):][:80])
check("P0 fixture: a Full Address row carries the whole address", "Full Address\n" + FULL + "\n" in T)

c = cmp_(HTML)
check("L1 localstar fixture: match", c["verdict"] == "match" and not c["wrong"] and not c["gaps"], c)
check("L1 NAP quotes the whole address", "100 Example Dr, Exampleton, KY 40000" in c["nap"], c["nap"])
check("L1 text-only read (no HTML) matches too", R.compare(T, CANON)["verdict"] == "match")

# L2 a wrong Full Address row is a mismatch, never match, never incomplete
for label, new, want in (("state", "100 Example Dr, Exampleton, TN 40000", ["state"]), ("ZIP", "100 Example Dr, Exampleton, KY 99999", ["zip"]),
                         ("city", "100 Example Dr, Otherville, KY 40000", ["city"]), ("street", "999 Other Rd, Exampleton, KY 40000", ["address"]),
                         ("state spelled out", "100 Example Dr, Exampleton, Tennessee 40000", ["state"])):
    c = cmp_(row(HTML, new))
    check("L2 Full Address row, wrong %s -> mismatch on %s" % (label, want[0]), c["verdict"] == "mismatch" and fields(c) == want, c)
c = cmp_(row(HTML, "100 Example Dr, Exampleton, Kentucky 40000"))
check("L2 state spelled out and right -> match", c["verdict"] == "match", c)

# L3 the row never loosens the compare
c = cmp_(row(HTML, "100 Example Dr, Exampleton"))
check("L3 partial Full Address row (no state / ZIP) -> still nap-incomplete", c["verdict"] == "nap-incomplete" and c["gaps"] == ["address"], c)
c = cmp_(HTML.replace("<strong>Full Address</strong>", "<strong>Mailing</strong>"))
check("L3 no Full Address label -> still nap-incomplete", c["verdict"] == "nap-incomplete" and c["gaps"] == ["address"], c)
other = HTML.replace("<span>Alder Care Consulting & Solutions</span>\n\t\t\t</li>\n \n\t\t\t<li class=\"fulladdress\">", "<span>Other Co Inc</span>\n\t\t\t</li>\n \n\t\t\t<li class=\"fulladdress\">")
check("L3 (setup) the Name row was swapped", other != HTML)
c = cmp_(other)
check("L3 Full Address row under another entity's name -> not used (nap-incomplete)", c["verdict"] == "nap-incomplete" and c["gaps"] == ["address"], c)
no_zip = dict(CANON, address="100 Example Dr, Exampleton, KY")
c = cmp_(HTML, no_zip)
check("L3 canonical without a ZIP is unverifiable -> the row does not close the gap", c["verdict"] == "nap-incomplete", c)
# a wrong visible locality under the street in the block is never overridden by the row
wrong_block = re.sub(r"(<span>100 Example Dr</span>\s*<span>) Exampleton(</span>)", r"\1 Otherville\2", HTML, count=1)
check("L3 (setup) the block city was swapped", wrong_block != HTML)
c = cmp_(wrong_block)
check("L3 wrong city in the Address Details block, right row -> not a match", c["verdict"] != "match", c)

# L4 the helper reads only a complete row
check("L4 full_address_row: none without the label", R.full_address_row("Name\n" + CANON["name"] + "\n" + FULL, CANON) is None)
check("L4 full_address_row: reads street / city / state / zip", R.full_address_row("Name\n" + CANON["name"] + "\nFull Address\n" + FULL, CANON) == {"street": "100 Example Dr", "city": "Exampleton", "state": "KY", "zip": "40000", "raw": FULL})

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
