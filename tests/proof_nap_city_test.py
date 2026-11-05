"""t_f2bc28d2: the proof nap quotes the city/state/zip line when the page puts it on its own line. Placeholder identities only."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "job"))
import recheck as R
CANON = {"name": "Alder Care Consulting & Solutions", "address": "100 Example Drive, Exampleton, KY 40000", "phone": "(502) 555-0101"}
PAD = " Lorem ipsum dolor sit amet." * 12
ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + ("" if c else "  " + str(d)))
def page(addr_lines): return "Home\nAlder Care Consulting & Solutions\n%s\n(502) 555-0101\n%s" % (addr_lines, PAD)
two = R.compare(page("100 Example Drive\nExampleton, Kentucky 40000"), CANON)
check("two-line: match", two["verdict"] == "match", two)
check("two-line: nap has street, city, state, zip", "100 Example Drive, Exampleton, KY 40000" in two["nap"], two["nap"])
check("two-line: nap keeps name and phone", two["nap"].startswith("Alder Care Consulting & Solutions | 100 Example Drive") and two["nap"].endswith("| (502) 555-0101"), two["nap"])
abbr = R.compare(page("100 Example Drive\nExampleton, KY 40000"), CANON)
check("two-line abbreviated state: city/state/zip in nap", abbr["verdict"] == "match" and "Exampleton, KY 40000" in abbr["nap"], abbr)
one = R.compare(page("100 Example Drive, Exampleton, KY 40000"), CANON)
check("one-line control: match, nap is name | street line | phone, no doubled city", one["verdict"] == "match" and one["nap"] == "Alder Care Consulting & Solutions | 100 Example Drive, Exampleton, KY 40000 | (502) 555-0101", one)
bad = R.compare(page("100 Example Drive\nOtherville, KY 40000"), CANON)
check("wrong city on the second line is still a mismatch", bad["verdict"] == "mismatch" and bad["wrong"], bad)
print(("ALL PASS (%d/%d)" if all(ok) else "FAILED (%d/%d)") % (sum(ok), len(ok))); sys.exit(0 if all(ok) else 1)
