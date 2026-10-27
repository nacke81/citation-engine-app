"""Every live row gets a NAP read on the next run (t_f6267312). Run: python tests/snapshot_live_nap_test.py (CI). No network, no browser: fetchers are in-memory fakes, urlopen is poisoned.
L1 match / wrong phone / unreadable page / not public / no listing URL: each stored as nap_check on the queue row, state and history untouched.
L2 after the run the snapshot overlay shows no live row with an unexplained null: each is True/False or null + a reasonText; summary recounted.
"""
import json, os, sys, tempfile, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ["CE_RUNS"] = tempfile.mkdtemp(prefix="ce-runs-")
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import recheck as R, buildqueue as Q, snapshot as SN, transitions as T  # noqa: E402

def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net
ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

DAY = "2026-10-28"
CANON = {"name": "Alder Care Consulting & Solutions", "address": "100 Example, Exampleton KY 40000", "phone": "(502) 555-0101"}
IDENT = json.load(open(os.path.join(HERE, "test_identity.json"), encoding="utf-8"))
PAD = " Lorem ipsum dolor sit amet." * 12
page = lambda phone="(502) 555-0101": "Home\nAlder Care Consulting & Solutions\n100 Example\nExampleton, KY 40000\n%s\n%s\n" % (phone, PAD)
U = {k: "https://%s.example/listing/%d" % (k, i) for i, k in enumerate("abcde", 1)}
row = lambda rid, d, url, **kw: dict({"id": rid, "directory": d + ".example", "state": "live", "mike_approval": None, "evidence_url": url, "history": [{"at": "2026-10-20", "from": "submitted", "to": "live"}]}, **kw)
rows = [row("l-match", "a", U["a"]), row("l-wrong", "b", U["b"]), row("l-unread", "c", U["c"]), row("l-nopub", "d", U["d"]), row("l-nourl", "e", None)]
pages = {U["a"]: page(), U["b"]: page("(502) 555-0199"), U["d"]: "Home\nThis listing is hidden until activated.\n" + PAD}
qp = os.path.join(tempfile.mkdtemp(), "q.json")
json.dump({"canonical": CANON, "fix_queue": rows}, open(qp, "w"))

def plain(url):
    v = pages.get(url)
    return R.Page(200, url, v) if v is not None else R.Page(404, url, "", err="HTTP 404")
chrome = lambda url: R.Page(0, url, "", err="none")
before = json.load(open(qp))
res = R.recheck(json.load(open(qp)), IDENT, plain=plain, chrome=chrome, record=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no transition may be recorded for a live row")),
                db=None, queue_path=qp, today=DAY, write=True, include_live=True)
after = json.load(open(qp))
by = {r["id"]: r for r in after["fix_queue"]}
check("L1 all five live rows were handled", len(res) == 5 and all("nap_check" in r for r in res))
check("L1 match -> True", by["l-match"]["nap_check"]["consistent"] is True and by["l-match"]["nap_check"]["at"] == DAY)
check("L1 wrong phone -> False naming phone with the shown value", by["l-wrong"]["nap_check"]["consistent"] is False and by["l-wrong"]["nap_check"]["fields"] == ["phone"] and by["l-wrong"]["nap_check"]["errors"][0]["live"] == "(502) 555-0199", str(by["l-wrong"]["nap_check"]))
check("L1 unreadable page -> None with a reason", by["l-unread"]["nap_check"]["consistent"] is None and bool(by["l-unread"]["nap_check"]["reason"]), str(by["l-unread"]["nap_check"]))
check("L1 hidden listing -> None with a reason", by["l-nopub"]["nap_check"]["consistent"] is None and bool(by["l-nopub"]["nap_check"]["reason"]), str(by["l-nopub"]["nap_check"]))
check("L1 no listing URL -> None with a reason", by["l-nourl"]["nap_check"]["consistent"] is None and "URL" in by["l-nourl"]["nap_check"]["reason"], str(by["l-nourl"]["nap_check"]))
check("L1 every row stays live, history unchanged", all(r["state"] == "live" and r["history"] == b["history"] for r, b in zip(after["fix_queue"], before["fix_queue"])))
dry = json.load(open(qp)); [r.pop("nap_check") for r in dry["fix_queue"]]; json.dump(dry, open(qp, "w"))
res2 = R.recheck(json.load(open(qp)), IDENT, plain=plain, chrome=chrome, record=None, db=None, queue_path=qp, today=DAY, write=False, include_live=True)
check("L1 a dry run reports nap_check but writes none", all("nap_check" in r for r in res2) and not any("nap_check" in r for r in json.load(open(qp))["fix_queue"]))

ov = Q.overlay_directories({"directories": []}, after["fix_queue"], DAY)
D = {d["domain"]: d for d in ov["directories"]}
check("L2 snapshot: match True, wrong False, three nulls", [D[x + ".example"]["napConsistent"] for x in "abcde"] == [True, False, None, None, None])
check("L2 every null live row carries a reasonText (none unexplained)", all(D[x + ".example"].get("reasonText") for x in "cde"))
check("L2 summary: live 5, napCorrect 1, napChecked 2", (ov["summary"]["live"], ov["summary"]["napCorrect"], ov["summary"]["napChecked"]) == (5, 1, 2), str(ov["summary"]))
print("\nALL PASS (%d/%d)" % (sum(ok), len(ok)) if all(ok) else "\nFAILED (%d/%d)" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
