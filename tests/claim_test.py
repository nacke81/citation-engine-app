"""Claim-status tests on scrubbed fixture pages (placeholder identity, no network). Run: python tests/claim_test.py  (CI does this).

C1 each verified marker   C2 a missing marker gives unknown (never claimed)   C3 site-wide footer text is not a marker
C4 unverified Directories are unknown   C5 queue rows (login / fix_method, idempotent, state + approval untouched)
C6 portal payload carries claim_status   C7 GET-only: read_claim only calls the getter with the page url
"""
import copy, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import claim as C  # noqa: E402
import portal as P  # noqa: E402
from cfg import IDENT  # noqa: E402

ok = []
def check(name, cond, detail=""):
    ok.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)

def fx(name): return C.html_to_text(open(os.path.join(HERE, "fixtures", "claim", name), encoding="utf-8").read())
DAY = "2026-10-20"
URL = {"mapquest.com": "https://www.mapquest.com/us/kentucky/alder-care-123456789",
       "merchantcircle.com": "https://www.merchantcircle.com/alder-care-exampleton-ky",
       "hotfrog.com": "https://www.hotfrog.com/company/EXAMPLE/alder-care/exampleton",
       "yellowpages.com": "https://www.yellowpages.com/exampleton-ky/mip/alder-care-123456789"}
def det(d, name): return C.detect(d, URL[d], fx(name), IDENT, "SCC", DAY)

# C1 positive markers
for d, name, want, quote in (("mapquest.com", "mapquest-unclaimed.html", "unclaimed", "Own this business? / Claim it"),
                             ("merchantcircle.com", "merchantcircle-unclaimed.html", "unclaimed", "Is this your business? / Claim your business now"),
                             ("hotfrog.com", "hotfrog-unclaimed.html", "unclaimed", "Is this your business? / Claim this business"),
                             ("yellowpages.com", "yellowpages-claimed.html", "claimed", "Claimed")):
    r = det(d, name)
    check("C1 %s %s marker -> %s" % (d, name, want), r["claim_status"] == want, r)
    e = r["claim_evidence"] or {}
    check("C1 %s evidence has exact text, url and date" % d, e.get("text") == quote and e.get("url") == URL[d] and e.get("date") == DAY and e.get("directory") == d, e)

# C2 no marker -> unknown, never claimed
for d, name in (("mapquest.com", "mapquest-no-marker.html"), ("merchantcircle.com", "merchantcircle-no-marker.html"),
                ("hotfrog.com", "hotfrog-no-marker.html"), ("yellowpages.com", "yellowpages-no-marker.html")):
    r = det(d, name)
    check("C2 %s with no marker -> unknown, no evidence" % d, r == {"claim_status": "unknown", "claim_evidence": None}, r)
check("C2 empty page -> unknown", C.detect("mapquest.com", URL["mapquest.com"], "", IDENT, "SCC", DAY)["claim_status"] == "unknown")
check("C2 a wall page (no listing text) -> unknown", C.read_claim("mapquest.com", URL["mapquest.com"], IDENT, "SCC", lambda u: (403, "<html>blocked</html>"), DAY)["claim_status"] == "unknown")
check("C2 a failed fetch -> unknown", C.read_claim("mapquest.com", URL["mapquest.com"], IDENT, "SCC", lambda u: (0, ""), DAY)["claim_status"] == "unknown")
check("C2 no url -> unknown", C.read_claim("mapquest.com", None, IDENT, "SCC", lambda u: (200, "x"), DAY)["claim_status"] == "unknown")

# C3 site-wide footer / nav claim text and script strings are not a marker
check("C3 MapQuest footer 'Claim your business' + claimedBy script alone is unknown", fx("mapquest-no-marker.html").count("Claim your business") == 1 and det("mapquest.com", "mapquest-no-marker.html")["claim_status"] == "unknown")
check("C3 script text is dropped from the page text", "claimedBy" not in fx("mapquest-unclaimed.html"))
check("C3 YellowPages footer 'Claim Your Listing' alone is unknown", det("yellowpages.com", "yellowpages-no-marker.html")["claim_status"] == "unknown")
check("C3 'Unclaimed' is never read as the Claimed badge", C.detect("yellowpages.com", URL["yellowpages.com"], "Alder Care\nUnclaimed\nSenior", IDENT, "SCC", DAY)["claim_status"] == "unknown")
check("C3 a search/category URL is never read as a record page", C.detect("mapquest.com", "https://www.mapquest.com/search/results?query=x", fx("mapquest-unclaimed.html"), IDENT, "SCC", DAY)["claim_status"] == "unknown")

# Hotfrog results page: only the CTA directly under THIS listing's block counts
res = "Page 1 - 2 results\nOther Plumbing LLC\nPlumber\n1 Main St, 40001 Elsewhere\nIs this your business? Claim this business\nAlder Care Consulting & Solutions\nHospice\n100 Example, 40000 Exampleton\nWrite a review"
check("C3 Hotfrog results page: another business's CTA is not ours", C.detect("hotfrog.com", "https://www.hotfrog.com/search/x", res, IDENT, "SCC", DAY)["claim_status"] == "unknown")
res2 = res.replace("Write a review", "x").replace("100 Example, 40000 Exampleton\nx", "100 Example, 40000 Exampleton\nIs this your business? Claim this business")
check("C3 Hotfrog results page: CTA under our own block -> unclaimed", C.detect("hotfrog.com", "https://www.hotfrog.com/search/x", res2, IDENT, "SCC", DAY)["claim_status"] == "unclaimed")

# C4 unverified Directories are unknown whatever the page says
for d in C.UNVERIFIED:
    r = C.detect(d, "https://%s/x/alder-care-123456789" % d, "Is this your business?\nClaim your business now\nOwn this business?\nClaim it\nClaimed", IDENT, "SCC", DAY)
    check("C4 %s (unverified) -> unknown" % d, r["claim_status"] == "unknown")
check("C4 the 7 unverified + 4 verified cover the 11 SCC found Directories", sorted(C.UNVERIFIED + tuple(C.RULES)) == sorted(["yellowpages.com", "superpages.com", "dexknows.com", "mapquest.com", "bing.com", "google.com", "maps.apple.com", "merchantcircle.com", "hotfrog.com", "cybo.com", "n49.com"]))

# C5 queue rows
q0 = json.load(open(os.path.join(HERE, "fixtures", "test_queue.json"), encoding="utf-8"))
q0["fix_queue"][0]["mike_approval"] = {"approved_by": "mike", "at": "2026-10-19", "row_id": "fix-a"}
q0["fix_queue"][0]["state"] = "submitted"
q0["fix_queue"][1]["fix_method"] = "suggest-edit"
claims = {"a.example": {"claim_status": "unclaimed", "claim_evidence": {"text": "t", "url": "u", "date": DAY, "directory": "a.example"}},
          "b.example": {"claim_status": "claimed", "claim_evidence": {"text": "Claimed", "url": "u", "date": DAY, "directory": "b.example"}},
          "c.example": {"claim_status": "unknown", "claim_evidence": None}}
q1 = C.merge_into_queue(copy.deepcopy(q0), claims)
ra, rb, rc, rd = q1["fix_queue"][0], q1["fix_queue"][1], q1["fix_queue"][2], q1["fix_queue"][3]
check("C5 unclaimed: fix_method claim + no-login text", ra["fix_method"] == "claim" and ra["login"] == "none: unclaimed, citation-submitter creates account under listings@" and ra["claim_status"] == "unclaimed")
check("C5 claimed: login 'client account needed', fix_method kept", rb["login"] == "client account needed" and rb["fix_method"] == "suggest-edit" and rb["claim_status"] == "claimed")
check("C5 unknown: login and fix_method unchanged", rc["login"] == q0["fix_queue"][2]["login"] and rc["fix_method"] == q0["fix_queue"][2]["fix_method"] and rc["claim_status"] == "unknown")
check("C5 a directory with no read is untouched", rd == q0["fix_queue"][3])
check("C5 state and mike_approval never overwritten", ra["state"] == "submitted" and ra["mike_approval"] == q0["fix_queue"][0]["mike_approval"] and all(a["state"] == b["state"] and a["mike_approval"] == b["mike_approval"] for a, b in zip(q1["fix_queue"], q0["fix_queue"])))
q2 = C.merge_into_queue(copy.deepcopy(q1), claims)
check("C5 merge is idempotent", q2 == q1)
q3 = C.merge_into_queue(copy.deepcopy(q1), {"a.example": {"claim_status": "unknown", "claim_evidence": None}})
check("C5 a later unknown read (blocked page) does not downgrade a known status", q3["fix_queue"][0]["claim_status"] == "unclaimed" and q3["fix_queue"][0]["login"] == ra["login"])
check("C5 queue rows still parse (buildqueue)", len(__import__("buildqueue").parse_rows(q1)) == 5)

# C6 portal payload: extra field only; counts and states unchanged
chk = [dict(biz="SCC", directory="mapquest.com", result="found", url=URL["mapquest.com"], method="m", note=None, diffs=[], _claim=det("mapquest.com", "mapquest-unclaimed.html")),
       dict(biz="SCC", directory="bing.com", result="found", url="https://www.bing.com/x", method="m", note=None, diffs=[]),
       dict(biz="SCC", directory="yelp.com", result="couldnt_check", url=None, method=None, note="blocked", diffs=None)]
p1 = P.build_payload(chk, DAY)
by = {d["domain"]: d for d in p1["directories"]}
check("C6 found row carries claim_status + evidence", by["mapquest.com"]["claim_status"] == "unclaimed" and by["mapquest.com"]["claim_evidence"]["text"].startswith("Own this business?"))
check("C6 found row with no read -> unknown", by["bing.com"]["claim_status"] == "unknown" and by["bing.com"]["claim_evidence"] is None)
check("C6 not-found row -> unknown", by["yelp.com"]["claim_status"] == "unknown")
p0 = P.build_payload([{k: v for k, v in c.items() if k != "_claim"} for c in chk], DAY)
strip = lambda p: {**p, "directories": [{k: v for k, v in d.items() if k not in ("claim_status", "claim_evidence")} for d in p["directories"]]}
check("C6 apart from the two extra fields the payload is identical (counts, states)", strip(p1) == strip(p0))

# C7 GET only
calls = []
C.read_claim("mapquest.com", URL["mapquest.com"], IDENT, "SCC", lambda u: (calls.append(u), (200, "<p>x</p>"))[1], DAY)
check("C7 read_claim makes exactly one call, with the page url only", calls == [URL["mapquest.com"]])
src = open(os.path.join(HERE, "..", "job", "claim.py"), encoding="utf-8").read()
check("C7 http_get sends no body and no non-GET method", "data=" not in src and "method=" not in src and "POST" not in src)

print("\n%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
