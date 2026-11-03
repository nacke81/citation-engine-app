"""Real yellowpagecity page stays match, street-only text stays nap-incomplete after #68 (t_57178c17). Pure, no network."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import claim
import recheck as R

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + ((" [%s]" % (d,)) if d else ""), flush=True)

CANON = {"name": "Alder Care Consulting & Solutions", "address": "100 Example Drive, Exampleton, KY 40000", "phone": "(502) 555-0101"}
v = R.compare("Alder Care Consulting & Solutions\n100 Example Drive\n(502) 555-0101", CANON, None)
check("F1 street only -> nap-incomplete, address gap", v["verdict"] == "nap-incomplete" and v["gaps"] == ["address"], v)
H = open(os.path.join(HERE, "fixtures", "yellowpagecity-scc-20261103.html"), encoding="utf-8").read()
check("F3 real yellowpagecity page -> match", R.compare(claim.html_to_text(H), CANON, H)["verdict"] == "match")
check("F3b same, text only", R.compare(claim.html_to_text(H), CANON)["verdict"] == "match")
SO = '<script type="application/ld+json">{"@type":"LocalBusiness","address":{"@type":"PostalAddress","streetAddress":"100 Example Drive"}}</script>'
v = R.compare("Home\nAlder Care Consulting & Solutions\n(502) 555-0101\nLorem ipsum dolor sit amet.\n", CANON, SO)
check("F4 structured street alone -> address gap", v["verdict"] == "nap-incomplete" and "address" in v["gaps"], v)
print("\nALL PASS" if all(ok) else "\nFAILED", "(%d/%d)" % (sum(ok), len(ok))); sys.exit(0 if all(ok) else 1)
