"""Category-fit filter tests (t_d13bd638). Run: python tests/fit_test.py (CI). No network: urlopen is poisoned, fetch and record are fakes."""
import os, sys, json, tempfile, shutil, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ["CE_RUNS"] = tempfile.mkdtemp(prefix="ce-runs-")
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import fit as F

def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

TMP = tempfile.mkdtemp()
PB = os.path.join(TMP, "pb"); os.makedirs(PB)

def row(dom, state="queued"):
    return {"id": "create-" + dom.split(".")[0], "directory": dom, "state": state, "kind": "create", "history": []}

def page(title="Local Business Directory", desc="Find local businesses", lang="en", status=200, dns=False, extra=""):
    html = '<html lang="%s"><head><title>%s</title><meta name="description" content="%s"></head><body>%s</body></html>' % (lang, title, desc, extra)
    return {"status": status, "html": html, "err": None, "dns": dns}

def cls(dom, cat=None, pb="", pg=None, others=()):
    r = row(dom)
    return F.classify(r, cat, pb, pg, [r] + list(others))

# ---- the seven batch 7 rows are known, with no fetch ----
for dom, want in (("here.com", "no-fit"), ("infobel.com", "no-fit"), ("activityhero.com", "no-fit"), ("vivinavi.com", "no-fit"),
                  ("fyple.com", "dead"), ("buildzoom.com", "no-fit"), ("accountantfinder.com", "no-fit")):
    v, why = cls(dom)
    check("F1 batch 7 row %s -> %s" % (dom, want), v == want and why, why)
check("F1 known rows need no homepage GET", True)

# ---- fit ----
v, why = cls("citylocalpro.com", {"category": "general"}, pg=page())
check("F2 general local Directory is fit", v == "fit", why)
v, why = cls("caring.com", {"category": "niche-senior"}, pg=page("Caring.com: Senior Living & Care Support", "family caregivers seeking in-home care"))
check("F2 senior-care Directory is fit", v == "fit" and "senior" in why, why)
v, why = cls("whatever.com", None, pg=None)
check("F2 no signal at all is fit", v == "fit", why)

# ---- dead ----
v, why = cls("gone.com", pg=page(status=0, dns=True)); check("F3 DNS failure is dead", v == "dead" and "DNS" in why, why)
v, why = cls("gone.com", pg={"status": 404, "html": "", "err": "HTTP 404", "dns": False}); check("F3 homepage 404 is dead", v == "dead", why)
v, why = cls("gone.com", pg={"status": 0, "html": "", "err": "ConnectionRefusedError", "dns": False}); check("F3 connection refused is dead", v == "dead", why)
v, why = cls("parked.com", pg=page(extra="This domain is for sale. Buy this domain today")); check("F3 parked domain is dead", v == "dead", why)
v, why = cls("old.com", {"category": "general", "dead": True, "dead_reason": "search 404"}); check("F3 Catalog dead flag is dead", v == "dead" and "search 404" in why, why)
v, why = cls("slow.com", pg=page(status=403)); check("F3 a 403 wall is NOT dead (fit)", v == "fit", why)
v, why = cls("slow.com", pg={"status": 0, "html": "", "err": "timeout", "dns": False}); check("F3 a timeout is NOT dead", v == "fit", why)

# ---- no-fit ----
v, why = cls("kidsfun.com", pg=page("Kids Activities Directory", "camps and classes for children")); check("F4 kids-only", v == "no-fit" and "kids" in why, why)
v, why = cls("proroofers.com", pg=page("Find licensed contractors near you", "Hire a contractor")); check("F4 contractors-only", v == "no-fit" and "contractors" in why, why)
v, why = cls("cpafind.com", pg=page("Accountant Finder", "Find an accountant or CPA")); check("F4 CPA-only", v == "no-fit" and "CPA" in why, why)
v, why = cls("devs.com", pg=page("Acme Location Platform", "Developer platform with maps API and SDK")); check("F4 developer platform", v == "no-fit" and "developer" in why, why)
v, why = cls("pages.de", pg=page()); check("F4 non-US ccTLD", v == "no-fit" and "non-US" in why, why)
v, why = cls("ok.com", pg=page(lang="ja")); check("F4 non-English html lang", v == "no-fit" and "non-English" in why, why)
v, why = cls("ok2.com", pg=page(lang="en-US")); check("F4 en-US lang is fine", v == "fit", why)
v, why = cls("jp.com", pb="Outcome: needs-human\nBlocker: Japanese-language Directory"); check("F4 playbook says non-English", v == "no-fit", why)
v, why = cls("steel.com", {"category": "niche-other"}, pg=page("Online Industrial and Manufacturing Directory", "Suppliers")); check("F4 industrial only", v == "no-fit", why)
v, why = cls("usdir.com", {"category": "general"}, pg=page("Find Local Businesses", "Search top-rated businesses, contractors, and professionals")); check("F4 general Directory that lists contractors among many trades stays fit", v == "fit", why)
v, why = cls("caregivers.com", {"category": "niche-senior"}, pg=page("Find senior care contractors", "home care for seniors")); check("F4 senior word in title keeps it fit", v == "fit", why)

# ---- duplicates ----
us = dict(row("us-info.com", "queued"), id="create-usinfo-com"); inf = dict(row("us-info.net", "queued"), id="create-usinfo-net")
v, why = F.classify(inf, None, "", page(), [inf, us]); check("F5 same brand other TLD: the later domain is the duplicate", v == "no-fit" and "duplicate of us-info.com" in why, why)
v, why = F.classify(us, None, "", page(), [us, inf]); check("F5 same brand: the first domain stays fit", v == "fit", why)
live = dict(row("listme.com", "live"), id="create-listme-com")
v, why = F.classify(dict(row("listme.net"), id="create-listme-net"), None, "", page(), [live]); check("F5 duplicate of a row already further along", v == "no-fit", why)

# ---- run_filter on a whole queue: only queued rows in build_order, fetch injected ----
q = {"canonical": {}, "build_order": ["create-a", "create-b", "create-c", "create-d", "create-here"],
     "create_queue": {"rows": [dict(row("a.com"), id="create-a"), dict(row("b.com", "live"), id="create-b"), dict(row("c.com"), id="create-c"),
                                dict(row("d.com"), id="create-d"), dict(row("here.com"), id="create-here"), dict(row("notordered.com"), id="create-n")]}}
calls = []
def fake_fetch(dom):
    calls.append(dom)
    return {"c.com": page(status=0, dns=True), "d.com": page(lang="de")}.get(dom, page())
res = F.run_filter(q, {}, PB, fake_fetch)
got = {r["id"]: v for r, v, _ in res}
check("F6 only queued rows in build_order are judged", set(got) == {"create-a", "create-c", "create-d", "create-here"}, str(sorted(got)))
check("F6 verdicts", got == {"create-a": "fit", "create-c": "dead", "create-d": "no-fit", "create-here": "no-fit"}, str(got))
check("F6 one homepage GET per judged unknown row, none for known rows", sorted(calls) == ["a.com", "c.com", "d.com"], str(calls))
check("F6 --row filter", [r["id"] for r, _, _ in F.run_filter(q, {}, PB, fake_fetch, only={"create-a"})] == ["create-a"])
n0 = len(calls); nf = F.run_filter(q, {}, PB, None); check("F6 no-fetch mode makes no GET and still judges known rows", len(calls) == n0 and {r["id"]: v for r, v, _ in nf}["create-here"] == "no-fit")
t = F.table(res)
check("F6 table has row, verdict, reason and a summary", "create-c" in t and "dead" in t and "fit 1, no-fit 2, dead 1 (of 4 queued rows)" in t, t.splitlines()[-1])

# ---- playbook text read ----
open(os.path.join(PB, "x.com.md"), "w", encoding="utf-8").write("# x.com - build playbook\nOutcome: needs-human\nSteps: 1. open\nSecret body line should not be read\nBlocker: Japanese-language only\n")
pt = F.playbook_text(PB, "x.com")
check("F7 playbook text keeps Outcome/Blocker/Steps lines only", "Blocker" in pt and "Outcome" in pt and "Secret body" not in pt)
check("F7 missing playbook is empty", F.playbook_text(PB, "nope.com") == "")

# ---- --write: rejects no-fit / dead through transitions, leaves fit alone, no Activities ----
rec = []
def fake_record(client, rid, new, ev, note, **kw):
    rec.append((client, rid, new, ev, note, kw)); return {"errors": []}
out = F.write_rejects(res, "unused.json", record=fake_record, today="2026-10-25")
check("F8 write rejects exactly the no-fit and dead rows", sorted(r[1] for r in rec) == ["create-c", "create-d", "create-here"], str([r[1] for r in rec]))
check("F8 target state is rejected, SCC only, reason in the note", all(r[0] == "SCC" and r[2] == "rejected" and r[3] is None for r in rec) and any("dead: DNS" in r[4] for r in rec))
check("F8 no client Activities row", all(r[5].get("activities_flag") is False for r in rec))
check("F8 results report ok", all(ok_ for _, ok_, _ in out) and len(out) == 3)
def failing(*a, **k): raise RuntimeError("boom")
out = F.write_rejects(res, "unused.json", record=failing)
check("F8 a refusal on one row is reported, not raised", len(out) == 3 and not any(o[1] for o in out))

# ---- real transitions.py path against a temp queue file (portal, activities and Directory DB off) ----
import transitions as T
class FakePortal:
    def __init__(self): self.calls = []
    def latest_snapshot(self, cid): return {"payload": {"found": 0, "directories": []}}
    def upsert_snapshot(self, cid, day, payload): self.calls.append(("snap", day))
    def call(self, *a, **k): self.calls.append(a)
qp = os.path.join(TMP, "q.json")
json.dump({"canonical": {}, "build_order": ["create-d"], "create_queue": {"rows": [dict(row("d.com"), id="create-d")]}}, open(qp, "w"))
fp = FakePortal(); os.environ["CE_DIRECTORIES_WRITE"] = "0"
res2 = F.run_filter(json.load(open(qp)), {}, PB, lambda d: page(lang="de"))
out = F.write_rejects(res2, qp, record=lambda *a, **k: T.record_transition(*a, portal=fp, **k), today="2026-10-25")
q2 = json.load(open(qp))
st = q2["create_queue"]["rows"][0]
check("F9 real transition: row is rejected with the fit reason in history", out[0][1] and st["state"] == "rejected" and "no-fit: non-English" in st["history"][-1]["note"], str(out))
check("F9 no Activities write", not any(len(c) > 1 and "deliverables" in str(c[1]) for c in fp.calls))

# ---- CLI never writes without --write ----
before = open(qp, "rb").read()
json.dump({"canonical": {}, "build_order": ["create-z"], "create_queue": {"rows": [dict(row("z.com"), id="create-z")]}}, open(qp, "w")); before = open(qp, "rb").read()
F.fetch_home = lambda d: page(lang="de")
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf): F.main(["--queue", qp, "--no-db", "--playbooks", PB])
check("F10 dry-run default writes nothing and prints the table", open(qp, "rb").read() == before and "create-z" in buf.getvalue() and "dry run: nothing written" in buf.getvalue())
check("F10 seed file fallback loads", len(F.load_catalog(False)[0]) > 50)

shutil.rmtree(TMP, ignore_errors=True)
print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})"); sys.exit(0 if all(ok) else 1)
