"""NM engine identity to R1 + Nate release gate (kanban t_00a75d04). Run: python tests/nm_r1_test.py (CI).
No network, no browser, no portal. Placeholder identity (tests/nm_r1_identity.json): Birch Media, 200 Sample Ave, Testville TN, alias Oldtown,
old streets 900 Old + 44 Prior, old phone 615-555-0112. It mirrors the real R1 shape: street, city-only rule, city alias, two old streets.

  N1 scoring: street + phone = match; "Testville, TN" with no street + phone = match; each old street = differing (not a match, address diff labelled old);
     old phone = differing; Gallatin-only + old phone is not a match; an old street next to the city-only form is not a match
  N2 discovery: search AND pattern plans cover the city and the alias; a listing that still reads the old city (alias) is still claimed
  N3 SCC unchanged: no city_only rule, no alias, single-city plan, city-only SCC page is not a match
  N4 gate: NM row with no approval refused; with Nate approval allowed; every malformed Nate approval refused; Nate approval on an SCC row refused;
     SCC row with null mike_approval refused as before, with Mike approval allowed as before; record() gets client NM for NM rows, SCC for SCC rows
  N5 release command: stamps only the named NM rows, backs up, leaves state/history/mike_approval alone; refuses wrong file, SCC id, unknown id, bad card,
     another card's release; same card again is a no-op; --dry-run writes nothing; the stamped row passes submit_row
"""
import copy, hashlib, json, os, re, sys, tempfile, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "nm_r1_identity.json")
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import core, judge, fixlist, cfg
import buildqueue as Q
import release as R

def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)
def raises(fn, exc):
    try: fn()
    except exc: return True
    except Exception: return False
    return False

IDENT = core.IDENT
def score(text, b="NM"):
    claim, ev, why = core.judge_listing(text, b)
    fl = judge.nap_flags({"ev": ev})
    diffs = fixlist.diffs_for(text, ev, IDENT, b, "https://dir.example/biz/x", labels=True)
    return claim, ev, fl, diffs

PH, OLDPH = "(615) 555-0111", "(615) 555-0112"
def page(street, cityline, phone, name="Birch Media"):
    return "\n".join(x for x in (name, street, cityline, phone) if x)

# ---- N1
c, ev, fl, dif = score(page("200 Sample Ave Ste 1", "Testville, TN 39999", PH))
check("N1 street + R1 phone = match", fl["match"] and fl["street_match"] and not [d for d in dif if d["field"] == "address"], (fl, dif))
c, ev, fl, dif = score(page(None, "Testville, TN", PH))
check("N1 city-only (no street) + R1 phone = match, claimed, no address diff", c and fl["match"] and not fl["street_match"] and fl["city_only"] and not dif, (fl, dif))
c, ev, fl, dif = score(page(None, "Testville, Tennessee", PH))
check("N1 'Testville, Tennessee' spelled out also = match", fl["match"], fl)
for old in ("44 Prior Blvd", "900 Old Rd"):
    c, ev, fl, dif = score(page(old, "Testville, TN 39999", PH))
    ad = [d for d in dif if d["field"] == "address"]
    check("N1 old street %r = differing" % old, (not fl["match"]) and fl["old_street"] and ad and ad[0].get("label") == "old address", (fl, dif))
    c, ev, fl, dif = score(page(old, "Testville, TN", PH))
    check("N1 old street %r next to the city-only form is NOT a match" % old, not fl["match"] and fl["old_street"] and not fl["city_only"], fl)
c, ev, fl, dif = score(page("200 Sample Ave Ste 1", "Testville, TN 39999", OLDPH))
ph = [d for d in dif if d["field"] == "phone"]
check("N1 old phone = differing (not a match, phone diff labelled old phone)", not fl["match"] and fl["stale_phone"] and ph and ph[0].get("label") == "old phone", (fl, dif))
c, ev, fl, dif = score(page(None, "Testville, TN", OLDPH))
check("N1 city-only + old phone is not a match", not fl["match"], fl)
c, ev, fl, dif = score(page(None, "Testville, TN", None))
check("N1 city-only with no phone is not a match", not fl["match"], fl)

# ---- N2
sp = core.plan_for("search", "yelp.com", "NM"); pp = core.plan_for("pattern", "yelp.com", "NM")
check("N2 search plan asks for the city and the alias", any("Testville" in u for _, u in sp) and any("Oldtown" in u for _, u in sp) and len(sp) == 2, sp)
check("N2 pattern plan has city and alias slugs", any("-testville" in u for _, u in pp) and any("-oldtown" in u for _, u in pp), pp)
hf = core.plan_for("search", "hotfrog.com", "NM")
check("N2 hotfrog (city in the path) covers both", any("/testville/" in u for _, u in hf) and any("/oldtown/" in u for _, u in hf), hf)
c, ev, fl, dif = score(page("900 Old Rd", "Oldtown, TN 39998", OLDPH))
check("N2 a listing under the old city + old street + old phone is still claimed (not lost)", c and ev["city"] and ev["old_street"], (c, ev))
c, ev, fl, dif = score(page("900 Old Rd", "Oldtown, TN 39998", PH))
check("N2 old city + old street + R1 phone is claimed and differing", c and not fl["match"] and fl["old_street"], (c, fl))

# ---- N3
check("N3 SCC has no alias and no city-only rule", cfg.cities("SCC") == ["Exampleton"] and "SCC" not in core.CITY_ONLY and "NM" in core.CITY_ONLY)
check("N3 SCC plan is one city", len(core.plan_for("search", "yelp.com", "SCC")) == 1)
c, ev, fl, dif = score("Alder Care Consulting & Solutions\nExampleton, KY\n(502) 555-0101", "SCC")
check("N3 SCC city-only page is NOT a match (street still required)", not fl["match"] and not fl["city_only"], fl)
c, ev, fl, dif = score("Alder Care Consulting & Solutions\n100 Example St\nExampleton, KY 40000\n(502) 555-0101", "SCC")
check("N3 SCC street + phone still a match", fl["match"], fl)
check("N3 nap_flags on an old-run ev (no city_only key) is unchanged", judge.nap_flags({"ev": {"name": True, "street": True, "phones": ["5025550101"]}})["match"] and not judge.nap_flags({"ev": {"name": True, "phones": ["5025550101"]}})["match"])

# ---- N4
NM = {"id": "nm-fix-yelp", "directory": "yelp.com", "kind": "fix", "state": "queued", "cost": "free", "vaultwarden_item": "yelp-nm", "mike_approval": None,
      "wrong_field": "phone", "right_value": "x"}
SCC = {"id": "fix-yelp", "directory": "yelp.com", "kind": "fix", "state": "queued", "cost": "free", "vaultwarden_item": "yelp-scc", "mike_approval": None}
login = lambda item: {"user": "u"}
NATE = lambda rid="nm-fix-yelp", **kw: dict({"by": "nate", "card": "t_76ce8d3c", "at": "2026-11-11T12:00:00-06:00", "row_id": rid}, **kw)
check("N4 NM row with no approval refused", raises(lambda: Q.submit_row(NM, login), Q.SubmitRefused))
def _msg(row):
    try: Q.submit_row(row, login)
    except Q.SubmitRefused as e: return str(e)
    return ""
check("N4 NM refusal names the Nate release; SCC refusal still names Mike", "Nate release" in _msg(NM) and "Mike approval" in _msg(SCC), (_msg(NM), _msg(SCC)))
res = Q.submit_row(dict(NM, approval=NATE()), login)
check("N4 NM row with Nate approval allowed (dry run to submitted)", res["dry_run"] is True and res["next_state"] == "submitted" and res["id"] == "nm-fix-yelp", res)
for name, a in (("by mike", NATE(by="mike")), ("no at", NATE(at="")), ("no card", NATE(card="")), ("card not a task id", NATE(card="abc")),
                ("other row id", NATE(rid="nm-fix-bbb")), ("no row_id", {k: v for k, v in NATE().items() if k != "row_id"}), ("not a dict", "nate")):
    check("N4 NM row with malformed Nate approval refused (%s)" % name, raises(lambda a=a: Q.submit_row(dict(NM, approval=a), login), Q.SubmitRefused))
check("N4 an SCC row with a Nate approval is still refused", raises(lambda: Q.submit_row(dict(SCC, approval=NATE("fix-yelp")), login), Q.SubmitRefused))
check("N4 an SCC-looking id cannot be passed off: nate_approval_ok false", not Q.nate_approval_ok(dict(SCC, approval=NATE("fix-yelp"))))
check("N4 SCC row with null mike_approval refused (as before)", raises(lambda: Q.submit_row(SCC, login), Q.SubmitRefused))
MIKE = lambda rid: {"approved_by": "mike", "at": "2026-10-19T16:00:00", "row_id": rid}
check("N4 SCC row with Mike approval allowed (as before)", Q.submit_row(dict(SCC, mike_approval=MIKE("fix-yelp")), login)["next_state"] == "submitted")
check("N4 NM row with a Mike approval still allowed (unchanged path)", Q.submit_row(dict(NM, mike_approval=MIKE("nm-fix-yelp")), login)["next_state"] == "submitted")
check("N4 SCC row, wrong-row Mike approval refused (as before)", raises(lambda: Q.submit_row(dict(SCC, mike_approval=MIKE("fix-bbb")), login), Q.SubmitRefused))
check("N4 paid NM row refused even with Nate approval", raises(lambda: Q.submit_row(dict(NM, approval=NATE(), cost="paid $9"), login), Q.SubmitRefused))
check("N4 NM row with no vault item refused even with Nate approval", raises(lambda: Q.submit_row(dict(NM, approval=NATE(), vaultwarden_item=None), login), Q.SubmitRefused))
seen = []
rec = lambda client, rid, to, url, note, **kw: seen.append((client, rid)) or {"ok": True}
Q.submit_row(dict(NM, approval=NATE()), login, record=rec)
Q.submit_row(dict(SCC, mike_approval=MIKE("fix-yelp")), login, record=rec)
check("N4 record() is called with client NM for an NM row and SCC for an SCC row", seen == [("NM", "nm-fix-yelp"), ("SCC", "fix-yelp")], seen)
import transitions as T
check("N4 transitions (SCC only) fail closed on an NM client", raises(lambda: T.record_transition("NM", "nm-fix-yelp", "submitted"), T.TransitionRefused))

# ---- N5
tmp = tempfile.mkdtemp()
def md5(p): return hashlib.md5(open(p, "rb").read()).hexdigest()
def mkq(name="nm-fix-queue.json"):
    p = os.path.join(tmp, name)
    q = {"business": "NM", "fix_queue": [dict(NM, id="nm-fix-yelp", history=[{"at": "x", "note": "n"}]), dict(NM, id="nm-fix-bbb", directory="bbb.org"),
                                         dict(NM, id="nm-fix-gone", directory="g.com", state="needs-human")], "revision": 3}
    json.dump(q, open(p, "w"), indent=2); return p
p = mkq(); before = json.load(open(p)); h0 = md5(p)
dry = R.release(p, ["nm-fix-yelp"], "t_76ce8d3c", write=False)
check("N5 dry run stamps nothing on disk", md5(p) == h0 and dry["released"] == ["nm-fix-yelp"] and dry["dry_run"])
out = R.release(p, ["nm-fix-yelp", "nm-fix-bbb"], "t_76ce8d3c")
after = json.load(open(p)); rows = {r["id"]: r for r in after["fix_queue"]}; brows = {r["id"]: r for r in before["fix_queue"]}
check("N5 release stamps by/card/at/row_id on the named rows", out["released"] == ["nm-fix-yelp", "nm-fix-bbb"] and rows["nm-fix-yelp"]["approval"]["by"] == "nate"
      and rows["nm-fix-yelp"]["approval"]["card"] == "t_76ce8d3c" and rows["nm-fix-bbb"]["approval"]["row_id"] == "nm-fix-bbb" and rows["nm-fix-yelp"]["approval"]["at"], rows["nm-fix-yelp"].get("approval"))
check("N5 the unnamed row is untouched", "approval" not in rows["nm-fix-gone"])
strip = lambda r: {k: v for k, v in r.items() if k != "approval"}
check("N5 state, history, mike_approval and every other field unchanged", all(strip(rows[i]) == brows[i] for i in rows) and after["revision"] == before["revision"] and all(r["mike_approval"] is None for r in rows.values()))
check("N5 backup written as .bak-<card> with the old content", os.path.exists(p + ".bak-t_76ce8d3c") and json.load(open(p + ".bak-t_76ce8d3c")) == before)
check("N5 a released row passes submit_row; an unreleased one does not", Q.submit_row(rows["nm-fix-yelp"], login)["next_state"] == "submitted" and raises(lambda: Q.submit_row(rows["nm-fix-gone"], login), Q.SubmitRefused))
h1 = md5(p); again = R.release(p, ["nm-fix-yelp"], "t_76ce8d3c")
check("N5 same card again is a no-op", again["released"] == [] and again["unchanged"] == ["nm-fix-yelp"] and md5(p) == h1)
check("N5 another card cannot overwrite a release", raises(lambda: R.release(p, ["nm-fix-yelp"], "t_0000aaaa"), R.ReleaseRefused) and md5(p) == h1)
for name, fn in (("wrong file name (SCC queue)", lambda: R.release(mkq("scc-fix-create-queue.json"), ["nm-fix-yelp"], "t_76ce8d3c")),
                 ("non-NM row id", lambda: R.release(p, ["fix-yelp"], "t_76ce8d3c")),
                 ("unknown row id", lambda: R.release(p, ["nm-fix-nope"], "t_76ce8d3c")),
                 ("card not a task id", lambda: R.release(p, ["nm-fix-gone"], "mike")),
                 ("no ids", lambda: R.release(p, [], "t_76ce8d3c")),
                 ("one bad id in a batch", lambda: R.release(p, ["nm-fix-gone", "nm-fix-nope"], "t_76ce8d3c"))):
    check("N5 refused: %s" % name, raises(fn, R.ReleaseRefused))
check("N5 a refused batch wrote nothing (nm-fix-gone still unstamped)", "approval" not in {r["id"]: r for r in json.load(open(p))["fix_queue"]}["nm-fix-gone"] and md5(p) == h1)
check("N5 CLI: refusal exits 2, success exits 0", R.main(["--release", "fix-yelp", "--card", "t_76ce8d3c", "--queue", p]) == 2 and R.main(["--release", "nm-fix-gone", "--card", "t_76ce8d3c", "--queue", p, "--dry-run"]) == 0)

# ---- N6 (r2) wrong street / old city
for txt, nm in ((page(None, "123 Main Street, Testville, TN 39999", PH).replace("\n", " "), "one-line wrong street"),
                (page("123 Main Street", "Testville, TN", PH), "multi-line wrong street + city-only form"),
                ("Birch Media 999 Wrong Rd Testville, TN " + PH, "wrong street, no comma before city")):
    c, ev, fl, dif = score(txt)
    ad = [d for d in dif if d["field"] == "address"]
    check("N6 %s + R1 phone = differing with an address diff" % nm, (not fl["match"]) and fl["other_street"] and not fl["city_only"] and ad, (fl, dif))
c, ev, fl, dif = score(page(None, "Testville, TN", PH + " Call 5551 now"))
check("N6 city-only with no street anywhere is still a match (digits in other text do not count as a street)", fl["match"] and fl["city_only"] and not fl["other_street"], fl)
c, ev, fl, dif = score(page(None, "Oldtown, TN", PH))
ad = [d for d in dif if d["field"] == "address"]
check("N6 alias city only (no street) + R1 phone = differing, address diff labelled old city", c and not fl["match"] and fl["old_city"] and ad and ad[0].get("label") == "old city" and ad[0]["canonical"], (c, fl, dif))
c, ev, fl, dif = score(page("200 Sample Ave", "Oldtown, TN", PH))
check("N6 R1 street under the old city is a match with no old-city diff (street wins)", fl["match"] and not [d for d in dif if d["field"] == "address"], (fl, dif))
c, ev, fl, dif = score(page(None, "Testville, TN", PH))
check("N6 primary city page never raises old city", not fl["old_city"] and fl["match"])
c, ev, fl, dif = score("Alder Care Consulting\n123 Main Street, Exampleton, KY\n(502) 555-0101", "SCC")
check("N6 SCC: no other_street / old_city flags, no extra diff beyond the street", not ev["other_street"] and not ev["old_city"], ev)

# ---- N7 (r2) NM state writer: release -> submit(live) -> state in the NM file
import nm_transitions as NT, transitions as T
p7 = mkq(); scc7 = os.path.join(tmp, "scc-fix-create-queue.json")
json.dump({"fix_queue": [dict(SCC, id="fix-yelp")], "revision": 1}, open(scc7, "w"), indent=2)
hs = md5(scc7); R.release(p7, ["nm-fix-yelp"], "t_76ce8d3c")
rows7 = {r["id"]: r for r in json.load(open(p7))["fix_queue"]}
NT.DEFAULT_NM_QUEUE = p7
_t = T.record_transition
T.record_transition = lambda *a, **k: (_ for _ in ()).throw(AssertionError("SCC writer called for an NM row"))
res = Q.submit_row(rows7["nm-fix-yelp"], login, live=True)
T.record_transition = _t
got = {r["id"]: r for r in json.load(open(p7))["fix_queue"]}["nm-fix-yelp"]
check("N7 release -> submit_row(live=True) -> NM row state=submitted in the NM file", got["state"] == "submitted" and res["recorded"]["to"] == "submitted", (got, res))
check("N7 history gained one entry (from queued to submitted, with note), earlier history kept", len(got["history"]) == 2 and got["history"][0]["note"] == "n" and got["history"][-1]["from"] == "queued"
      and got["history"][-1]["to"] == "submitted" and got["history"][-1]["note"], got["history"])
check("N7 approval stamp and mike_approval untouched", got["approval"] == rows7["nm-fix-yelp"]["approval"] and got["mike_approval"] is None)
check("N7 other NM rows untouched", {r["id"]: r for r in json.load(open(p7))["fix_queue"]}["nm-fix-bbb"] == rows7["nm-fix-bbb"])
check("N7 SCC queue md5 unchanged", md5(scc7) == hs)
check("N7 backup .bak-nm-<day> written once with the pre-write content", any(f.startswith("nm-fix-queue.json.bak-nm-") for f in os.listdir(tmp)))
check("N7 NM writer refuses an SCC client / SCC file / SCC row id / no note / a bad move",
      raises(lambda: NT.record_transition("SCC", "nm-fix-bbb", "submitted", note="x", queue_path=p7), T.TransitionRefused)
      and raises(lambda: NT.record_transition("NM", "fix-yelp", "submitted", note="x", queue_path=scc7), T.TransitionRefused)
      and raises(lambda: NT.record_transition("NM", "nm-fix-bbb", "submitted", note="x", queue_path=scc7), T.TransitionRefused)
      and raises(lambda: NT.record_transition("NM", "fix-yelp", "submitted", note="x", queue_path=p7), T.TransitionRefused)
      and raises(lambda: NT.record_transition("NM", "nm-fix-bbb", "submitted", note="", queue_path=p7), T.TransitionRefused)
      and raises(lambda: NT.record_transition("NM", "nm-fix-bbb", "live", evidence_url="https://x.example/p", note="x", queue_path=p7), T.TransitionRefused)   # queued -> live not allowed
      and md5(scc7) == hs)
check("N7 a row with no release is refused by submit_row before the writer runs", raises(lambda: Q.submit_row(rows7["nm-fix-bbb"], login, live=True), Q.SubmitRefused)
      and {r["id"]: r for r in json.load(open(p7))["fix_queue"]}["nm-fix-bbb"]["state"] == "queued")
check("N7 CLI: refusal exits 2, success exits 0, dry run writes nothing", NT.main(["--row", "nm-fix-bbb", "--to", "live", "--note", "x", "--queue", p7]) == 2
      and (lambda h: NT.main(["--row", "nm-fix-bbb", "--to", "submitted", "--note", "sent", "--queue", p7, "--dry-run"]) == 0 and md5(p7) == h)(md5(p7))
      and NT.main(["--row", "nm-fix-bbb", "--to", "submitted", "--note", "sent", "--queue", p7]) == 0)

# ---- N8 (r3) other_street is scoped to NM's own card, directly before the city, and to the JSON-LD entity named NM
def clean(txt, nm):
    c, ev, fl, dif = score(txt)
    ad = [d for d in dif if d["field"] == "address"]
    return c and fl["match"] and not fl["other_street"] and not ad, (fl, dif)
card = page(None, "Testville, TN", PH)
n8 = {
    "(a) n49 shape: NM card, then a Similar Businesses list of neighbours with streets":
        card + "\nGet Directions\nSimilar Businesses\nSee All\nVML\n401 Church Street, Floor 18, Testville, TN (8 Km Away)\n5.0\nP.O.G. LLC\n4004 Hillsboro Pike, Suite 202-A, Testville, TN (1 Km Away)",
    "(a2) mapquest shape: Also at this address list of neighbours":
        card + "\nAlso at this address\nPop Mt\n12 Oak Street, Testville, TN\nMcNally Law",
    "(a3) a neighbour listing ABOVE NM's card":
        "Search results\nPop Mt\n500 Main St, Testville, TN\n(615) 555-0199\n" + card,
    "(b) the directory's own Organization JSON-LD with its own streetAddress":
        '{"@type":"Organization","name":"DirCo","address":{"@type":"PostalAddress","streetAddress":"100 Corporate Dr","addressLocality":"Austin"}}\n' + card,
    "(b2) NM-named entity with only a place phrase in streetAddress":
        '{"@type":"LocalBusiness","name":"Birch Media","address":{"streetAddress":"Serving Testville area"}}\n' + card,
    "(c) prose 'find their way' before the city":
        "Birch Media\nWe have helped 100 local businesses find their way online. Testville, TN\n" + PH,
    "(d) 'N reviews from Dr.' next to the city (same line)":
        "Birch Media\n4 reviews from Dr. Smith, Testville, TN\n" + PH,
    "(d2) 'N reviews from Dr.' on the line above the city":
        "Birch Media\n4 reviews from Dr.\nTestville, TN\n" + PH,
}
for nm, txt in n8.items():
    r, d = clean(txt, nm); check("N8 %s = match, no address diff" % nm, r, d)
bad = '{"@type":"LocalBusiness","name":"Birch Media","address":{"streetAddress":"123 Main Street"}}\n' + card
c, ev, fl, dif = score(bad)
check("N8 an NM-named entity with a wrong streetAddress = differing + address diff", (not fl["match"]) and fl["other_street"] and [d for d in dif if d["field"] == "address"], (fl, dif))
c, ev, fl, dif = score("Birch Media 123 Main Street, Testville, TN 39999 " + PH + "\nSimilar Businesses\n9 Elm St, Testville, TN")
check("N8 one-line wrong street (name first) is still differing with the address diff naming it, not the neighbour",
      (not fl["match"]) and ev["other_street"] == "123 Main Street" and [d["live"] for d in dif if d["field"] == "address"] == ["123 Main Street"], (ev["other_street"], dif))
c, ev, fl, dif = score(page("123 Main Street", "Testville, TN", PH) + "\nSimilar Businesses\n9 Elm St, Testville, TN")
check("N8 wrong street directly above the city in NM's card is still differing", (not fl["match"]) and ev["other_street"] == "123 Main Street", ev["other_street"])
c, ev, fl, dif = score(page("123 Main Street, Ste 4", "Testville, TN", PH))
check("N8 a suite between the street and the city does not hide the wrong street", (not fl["match"]) and ev["other_street"].startswith("123 Main Street"), ev["other_street"])
# mutation: widen the scope back to the whole page -> the n49 shape (a) must fail
_ob = core._own_block
core._own_block = lambda text, b: [l.strip() for l in (text or "").split("\n") if l.strip()]
r, d = clean(n8["(a) n49 shape: NM card, then a Similar Businesses list of neighbours with streets"], "a")
core._own_block = _ob
check("N8 MUTATION widen the scope to the whole page -> case (a) fails (the test bites)", not r)
# mutation: take streetAddress from any entity -> case (b) fails
_nm = core.NAME["NM"]
core.NAME["NM"] = re.compile(r".", re.S)      # the entity-name test always passes (DirCo counts as NM)
r, d = clean(n8["(b) the directory's own Organization JSON-LD with its own streetAddress"], "b")
core.NAME["NM"] = _nm
check("N8 MUTATION any-entity streetAddress (name test off) -> case (b) fails", not r)

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
