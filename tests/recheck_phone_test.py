"""Recheck phone-reading regression tests (t_032083dc). Run: python tests/recheck_phone_test.py (CI). No network: saved copies of the real pages
(tests/fixtures/recheck/*) fed to recheck.compare. hotfrog + freelistingusa are the raw HTML of the public page (text derived with claim.html_to_text);
foursquare is the rendered text from the build Chrome (the plain page is a JS login shell)."""
import os, sys, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import recheck as R
import claim

def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

FX = os.path.join(HERE, "fixtures", "recheck")
def rd(n): return open(os.path.join(FX, n), encoding="utf-8").read()
CANON = {"name": "Senior Care Consulting & Solutions", "address": "93 Montrose Drive, Madisonville KY 42431", "phone": "(270) 841-2550"}

# 1 hotfrog: the Verified ID uuid must not be read as a phone; structured data carries the phone
h = rd("hotfrog.html"); c = R.compare(claim.html_to_text(h), CANON, h)
check("hotfrog real page: match (no phone mismatch from the UUID)", c["verdict"] == "match" and not c["wrong"], str(c["wrong"]))
check("hotfrog: uuid line gives no phone", R.phones_in(["Verified ID: 00999496-673d-7825-8e2d-7780175522c0"]) == [])
check("hotfrog: structured phones come from tel:/JSON-LD", len(R.structured_phones(h)) >= 1)

# 2 freelistingusa: the name also appears in breadcrumbs above a claim panel; the NAP follows the panel
f = rd("freelistingusa.html"); c = R.compare(claim.html_to_text(f), CANON, f)
check("freelistingusa real page: match (no gap phone/address)", c["verdict"] == "match" and not c["gaps"], str(c))
c2 = R.compare(claim.html_to_text(f), CANON)
check("freelistingusa: match from text alone too", c2["verdict"] == "match", str(c2))

# 3 foursquare: the page itself shows a wrong phone (+27 84 125 50), so mismatch phone is the true reading, not a parser fault
t = rd("foursquare.txt"); c = R.compare(t, CANON)
check("foursquare real page: still mismatch phone (the public number is wrong)", c["verdict"] == "mismatch" and c["wrong"] and c["wrong"][0][0] == "phone" and "+27 84 125 50" in c["wrong"][0][1], str(c["wrong"]))
check("foursquare: not mistaken for a match or a gap", c["verdict"] not in ("match", "gap"))

# 4 phone-shaped boundaries
for tok in ("ID a7780175522c0x", "Ref 2708412550x", "ab2708412550", "id-2708412550-ab12"):
    check("no phone inside token: " + tok, R.phones_in([tok]) == [], str(R.phones_in([tok])))
check("plain phone still read", R.phones_in(["Call (270) 841-2550 today"]) == ["2708412550"])
check("dashed phone still read", R.phones_in(["270-841-2550"]) == ["2708412550"])

# 5 masked phones
MASK = "+127" + "*" * 4 + "2550"
check("masked visible digits agree -> True", R.masked_match(MASK, "2708412550") is True)
check("masked visible digits disagree -> False", R.masked_match("+127" + "*" * 4 + "9999", "2708412550") is False)
check("not masked -> None", R.masked_match("(270) 841-2550", "2708412550") is None)
page_txt = "Home\nSenior Care Consulting & Solutions\n%s\nseniorcaresolutions.co\n93 Montrose Drive, 42431\nMadisonville\nShow map\n" % MASK + "pad " * 80
c = R.compare(page_txt, CANON)
check("masked phone in text: match (masked), not mismatch or gap", c["verdict"] == "match" and c["masked"] and MASK in c["nap"], str(c))
ld = '<script type="application/ld+json">{"telephone":["%s"]}</script>' % MASK
c = R.compare(page_txt.replace(MASK, "Show phone"), CANON, ld)
check("masked JSON-LD telephone: match (masked)", c["verdict"] == "match" and c["masked"], str(c))
bad = '<a href="tel:+127%s9999">x</a>' % ("*" * 4)
c = R.compare(page_txt, CANON, bad)
check("masked phone whose visible digits disagree: mismatch phone", c["verdict"] == "mismatch" and c["wrong"][0][0] == "phone", str(c))
rows = [{"row": "r", "before": "submitted", "after": "live", "verdict": "match", "fields": [], "error": None, "masked": True}]
check("report line says match (masked)", "match (masked)" in R.format_report(rows))

# 6 structured data wins over free text
ld_ok = '<script type="application/ld+json">{"telephone":"+1 270 841 2550"}</script><a href="tel:+12708412550">c</a>'
txt = "Home\nSenior Care Consulting & Solutions\n(502) 555-0101\n93 Montrose Drive, Madisonville, KY 42431\n" + "pad " * 80
c = R.compare(txt, CANON, ld_ok)
check("structured tel agrees -> match even if a stray text phone differs", c["verdict"] == "match", str(c))
ld_wrong = '<a href="tel:+15025550101">c</a>'
c = R.compare(txt.replace("(502) 555-0101", "(270) 841-2550"), CANON, ld_wrong)
check("structured tel differs -> mismatch phone", c["verdict"] == "mismatch" and c["wrong"][0][0] == "phone", str(c))

# 7 name strictness kept (PR #28)
typo = "Home\nSenior Care Consltng Solutions\n93 Montrose Drive\nMadisonville, KY 42431\n(270) 841-2550\n" + "pad " * 80
c = R.compare(typo, CANON)
check("Consltng typo still mismatch name", c["verdict"] == "mismatch" and any(w[0] == "name" for w in c["wrong"]), str(c["wrong"]))
good = typo.replace("Consltng Solutions", "Consulting & Solutions")
check("exact name + exact NAP still match", R.compare(good, CANON)["verdict"] == "match")

print("\n%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
