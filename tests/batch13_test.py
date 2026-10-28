"""Batch 13 fix tests (t_3ac43137): signed-out reader (own Chrome, never 9333), hidden phone reveal, hidden banner = nap-incomplete, not-public verdict,
vault item resolution by domain, --row lookup across all queue lists, listing URL captured at submit. No network, no browser, no vault.
Run: python tests/batch13_test.py (CI)."""
import os, sys, json, shutil, tempfile, types, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ["CE_RUNS"] = tempfile.mkdtemp(prefix="ce-runs-")
JOB = os.path.join(HERE, "..", "job")
sys.path.insert(0, JOB)
import recheck as R, build_runner as B, buildqueue as Q, vault_item as VI, listing_capture as LC, listing as L, transitions as T

def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net
ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

TMP = tempfile.mkdtemp(prefix="b13-")
CANON = {"name": "Alder Care Consulting & Solutions", "address": "100 Example Drive, Exampleton KY 40000", "phone": "(502) 555-0101"}
PAD = " Lorem ipsum dolor sit amet." * 12
def body(phone="(502) 555-0101", extra=""):
    return "Home\nAlder Care Consulting & Solutions\n100 Example Drive\nExampleton, KY 40000\n%s\n%s\n%s" % (phone, extra, PAD)

# ---- A1 reader: own Chrome, clean profile, never 9333 --------------------------------------------------------------------
class FakeOC:
    made = []
    def __init__(s, port=51234): s.port, s.entered, s.exited = port, False, False; FakeOC.made.append(s)
    def __enter__(s): s.entered = True; return s
    def __exit__(s, *a): s.exited = True; return False
    @property
    def cdp_url(s): return "http://127.0.0.1:%s" % s.port
seen = []
def fetcher(url, cdp, wait_s): seen.append(cdp); return R.Page(200, url, body(), [], html=None)
rd = R.SignedOutReader(chrome_factory=FakeOC, fetcher=fetcher)
p1 = rd("https://a.example/1"); p2 = rd("https://a.example/2")
check("A1 reader starts its own Chrome once, on its own port (not 9333)", len(FakeOC.made) == 1 and FakeOC.made[0].entered and seen == ["http://127.0.0.1:51234"] * 2 and R.CDP_URL not in seen)
rd.close()
check("A1 close() shuts the Chrome down", FakeOC.made[0].exited and rd.chrome is None)
FakeOC.made.clear(); seen.clear()
bad = R.SignedOutReader(chrome_factory=lambda: FakeOC(9333), fetcher=fetcher)
pg = bad("https://a.example/1")
check("A1 a reader that lands on 9333 refuses to read (never the signed-in build profile)", pg.status == 0 and "did not start" in (pg.err or "") and seen == [] and FakeOC.made[0].exited, str(pg.err))
dead = R.SignedOutReader(chrome_factory=lambda: (_ for _ in ()).throw(OSError("no chrome")), fetcher=fetcher)
check("A1 a Chrome that will not start gives an error page, no raise", dead("https://a.example/1").status == 0)
src = open(os.path.join(JOB, "recheck.py"), encoding="utf-8").read()
check("A1 default reader is OwnedChrome (throwaway profile, random port): no persistent profile or fixed port passed", "OC.OwnedChrome()" in src and "OwnedChrome(profile" not in src and "OwnedChrome(port" not in src)

# ---- A2 recheck uses the plain path first, falls back to the reader, closes it ---------------------------------------------
def row(rid, d, state, url, **kw): return dict({"id": rid, "directory": d, "state": state, "evidence_url": url, "cost": "free", "history": []}, **kw)
def queue(rows):
    q = {"canonical": CANON, "fix_queue": [], "create_rows": [], "create_queue": {"rows": rows}}
    p = os.path.join(TMP, "q.json"); json.dump(q, open(p, "w")); return p, q
IDENT = json.load(open(os.path.join(HERE, "test_identity.json"), encoding="utf-8"))
U = "https://js.example/biz/alder"
calls = {"plain": 0, "reader": 0, "closed": 0}
class Rd:
    def __init__(s, pages): s.pages = pages
    def __call__(s, url): calls["reader"] += 1; return s.pages[url]
    def close(s): calls["closed"] += 1
def plain_js(url): calls["plain"] += 1; return R.Page(200, url, "Loading...")   # JS page: curl sees a shell
_, q = queue([row("create-js", "js.example", "submitted", U)])
res = R.recheck(q, IDENT, plain=plain_js, chrome=Rd({U: R.Page(200, U, body())}), record=lambda *a, **k: {}, today="2026-11-02", write=False)
check("A2 curl first, then the real-Chrome reader on 'not readable': match", calls["plain"] == 1 and calls["reader"] == R.STABLE_READS and res[0]["verdict"] == "match" and res[0]["via"] == "chrome", str(res))
check("A2 the result carries the parsed NAP for the report", res[0]["nap"] and "555-0101" in res[0]["nap"], str(res[0].get("nap")))
check("A2 a dry run never changed the row", q["create_queue"]["rows"][0]["state"] == "submitted" and not q["create_queue"]["rows"][0]["history"])

# ---- A3 verdicts for pages that used to be 'not readable' ------------------------------------------------------------------
LOGIN = R.Page(200, "https://app.js.example/login?continue=%2Fv%2Fx", "Log in to Directory\n\nEnter your email or phone to receive a login code\n\nEmail or phone number\nContinue")
NF = R.Page(200, U, "Support\nLogin Now\nLog In\nRegister\n\nWe couldn't find \"Alder Care Consulting & Solutions\"\nHere are some similar businesses\nOther Co\nRating 0")
E404 = R.Page(404, U, "Page not found " * 20)
WALL = R.Page(200, U, "Just a moment... " * 20)
EMPTY = R.Page(0, U, "", err="TimeoutError")
for label, pg, want in (("login redirect", LOGIN, "not-public"), ("'We couldn't find' page", NF, "not-public"), ("HTTP 404", E404, "not-public"),
                        ("Cloudflare wall", WALL, "unreadable"), ("timeout / error page", EMPTY, "unreadable")):
    _, q = queue([row("create-js", "js.example", "submitted", U)])
    res = R.recheck(q, IDENT, plain=lambda u: R.Page(200, u, "Loading..."), chrome=Rd({U: pg}), record=lambda *a, **k: {}, today="2026-11-02", write=False)
    check("A3 %s -> %s" % (label, want), res[0]["verdict"] == want, str(res[0]))
    check("A3 %s writes nothing" % label, not q["create_queue"]["rows"][0]["history"])
res = R.recheck(queue([row("create-js", "js.example", "submitted", U)])[1], IDENT, plain=lambda u: R.Page(200, u, "Loading..."), chrome=Rd({U: LOGIN}), record=lambda *a, **k: {}, write=False)
check("A3 not-public carries a reason in the note", "login" in (res[0]["note"] or ""), str(res[0]["note"]))
check("A3 not-public from a plain (curl) page is never guessed: needs a rendered or 404 read", R.not_public(R.Page(200, U, "x" * 300), "plain") is None)

# ---- B1 hidden phone: click Reveal, then parse ----------------------------------------------------------------------------
class PG:
    """A page whose phone appears only after the Reveal control is clicked (us-info)."""
    def __init__(s, hidden=True): s.revealed, s.url, s.hidden, s.evals = False, "https://us.example/b", hidden, []
    def goto(s, u, **k): return types.SimpleNamespace(status=200)
    def wait_for_timeout(s, ms): pass
    def inner_text(s, sel, timeout=0): return body("Reveal Phone Number" if s.hidden and not s.revealed else "(502) 555-0101")
    def evaluate(s, js):
        s.evals.append(js)
        if "RegExp" in js:
            if s.hidden and not s.revealed: s.revealed = True; return 1
            return 0
        return []
    def content(s): return "<html></html>"
pg = PG()
st, text, links, raw = R.read_rendered(pg, "https://us.example/b", wait_s=2)
check("B1 'Reveal Phone Number' is clicked and the revealed phone is parsed -> match", pg.revealed and R.compare(text, CANON)["verdict"] == "match", text[:90])
check("B1 before the click the same page is nap-incomplete (phone hidden), not mismatch", R.compare(body("Reveal Phone Number"), CANON)["verdict"] == "nap-incomplete")
pg2 = PG(hidden=False); R.read_rendered(pg2, "https://us.example/b", wait_s=2)
check("B1 a page with no reveal control is not clicked again or reparsed", not pg2.revealed)
check("B1 the reveal pattern matches the reveal/show/view phone labels only", all(__import__("re").search(R.REVEAL_RE, t, 2) for t in ("Reveal Phone Number", "Show phone", "Click to call")) and not __import__("re").search(R.REVEAL_RE, "Submit your listing", 2))

# ---- B2 HIDDEN / paused banner is not-public even on a partial parse ---------------------------------------------------
HID = "HIDDEN until ACTIVATED"
c = R.compare(body(extra=HID), CANON)
check("B2 NAP all matches but a HIDDEN banner -> not-public, not match", c["verdict"] == "not-public" and "listing visibility" in c["gaps"], str(c))
c = R.compare(body(phone="(502) 555-0199", extra=HID), CANON)
check("B2 HIDDEN banner beats a wrong phone: not-public", c["verdict"] == "not-public", str(c))
c = R.compare("Alder Care Consulting & Solutions\n%s\n%s" % (HID, PAD), CANON)
check("B2 partial parse (name only) with the banner -> not-public", c["verdict"] == "not-public", str(c))
c = R.compare("%s\nSomething else entirely\n%s" % (HID, PAD), CANON)
check("B2 banner and no parseable block -> not-public, not unreadable", c["verdict"] == "not-public", str(c))
c = R.compare("This listing is paused\n" + body(), CANON)
check("B2 'paused' banner -> not-public", c["verdict"] == "not-public")
check("B2 the same page without a banner still matches", R.compare(body(), CANON)["verdict"] == "match")
_, q = queue([row("create-sml", "js.example", "created-unlisted", U)])
res = R.recheck(q, IDENT, plain=lambda u: R.Page(200, u, body(extra=HID)), chrome=None, record=lambda *a, **k: {}, today="2026-11-02", write=False)
check("B2 a created-unlisted row with the banner never goes live", res[0]["verdict"] == "not-public" and res[0]["after"] == "created-unlisted", str(res[0]))

# ---- C1 vault item by registrable domain -----------------------------------------------------------------------------------
ITEMS = [{"id": "id-acompio", "name": "SCC - acompio", "uris": ["https://account.acompio.com/login"]},
         {"id": "id-4sq", "name": "SCC - foursquare.com (rotated 10-25)", "uris": ["https://foursquare.com/login"]},
         {"id": "id-clp", "name": "SCC - citylocalpro.com", "uris": ["https://citylocalpro.com/"]},
         {"id": "id-tup", "name": "SCC - tupalo.co", "uris": []},
         {"id": "id-yp", "name": "SCC - accounts.yellowpages.com (Thryv)", "uris": ["https://accounts.yellowpages.com/"]},
         {"id": "id-uri", "name": "SCC login 7", "uris": ["https://www.listyourbusiness.us/login"]}]
check("C1 spec 'SCC - acompio.com' resolves the item named 'SCC - acompio'", VI.resolve_item("acompio.com", ITEMS)["id"] == "id-acompio")
check("C1 the queue's TLD (acompio.us) resolves it too (same brand, name match)", VI.resolve_item("acompio.us", ITEMS)["id"] == "id-acompio")
check("C1 foursquare resolves by name that CONTAINS the domain", VI.resolve_item("foursquare.com", ITEMS)["name"].startswith("SCC - foursquare.com"))
check("C1 www./sub-domain input reduces to the registrable domain", VI.resolve_item("www.citylocalpro.com", ITEMS)["id"] == "id-clp" and VI.registrable("accounts.yellowpages.com") == "yellowpages.com" and VI.registrable("a.b.example.co.uk") == "example.co.uk")
check("C1 an item matched only by its login URI resolves", VI.resolve_item("listyourbusiness.us", ITEMS)["id"] == "id-uri")
check("C1 exact 'SCC - <domain>' beats a looser name match", VI.resolve_item("tupalo.co", ITEMS + [{"id": "x", "name": "tupalo.co notes", "uris": []}])["id"] == "id-tup")
for d in ("nothere.com", ""):
    try: VI.resolve_item(d, ITEMS); r = None
    except VI.VaultItemError as e: r = str(e)
    check("C1 no item for %r -> not-found error" % d, r and "not-found" in r, str(r))
try: VI.resolve_item("acompio.com", ITEMS + [{"id": "dup", "name": "SCC - acompio", "uris": ["https://account.acompio.com/"]}]); r = None
except VI.VaultItemError as e: r = str(e)
check("C1 two best matches -> item-not-unique, names listed, asks for --item-id", r and "item-not-unique" in r and "--item-id" in r, str(r))
try: VI.resolve_item("evil.com", [{"id": "z", "name": "SCC - notevil.com", "uris": []}]); r = None
except VI.VaultItemError as e: r = str(e)
check("C1 a lookalike (notevil.com for evil.com) is not matched on the brand rule", r and "not-found" in r, str(r))

class Proc:
    def __init__(s, rc, out): s.returncode, s.stdout, s.stderr = rc, out, ""
class Runner:
    def __init__(s, plan): s.calls, s.plan = [], list(plan)
    def __call__(s, cmd, **k): s.calls.append(cmd); return Proc(*s.plan.pop(0))
LISTING = json.dumps({"items": ITEMS})
site = types.SimpleNamespace(name="acompio", domain="acompio.com", vault_item="SCC - acompio.com")
nap = B.nap_from_identity(IDENT)
rn = Runner([(1, "fill=failed reason=not-found"), (0, LISTING), (0, "lookup=success matches=1 item=(id id-acompio)")])
c = B.Ctx(site, None, nap, runner=rn, dry_run=True, log=lambda *a: None)
out = c.vault_fill("#p", "https://account.acompio.com/signup.php")
second = rn.calls[2]
check("C1 vault_fill: not-found -> lists the Citations collection -> retries once with --item-id", len(rn.calls) == 3 and "vault_resolve.cjs" in rn.calls[1][1] and "--item-id" in second and second[second.index("--item-id") + 1] == "id-acompio" and "--name" not in second, str(rn.calls))
check("C1 the resolved id is kept for later fills (one list per run)", c.item_id == "id-acompio")
rn2 = Runner([(0, "fill=success field=x item=y")])
fake_page = types.SimpleNamespace(url="https://account.acompio.com/s", bring_to_front=lambda: None)
c2 = B.Ctx(site, fake_page, nap, runner=rn2, dry_run=False, item_id="given-id", log=lambda *a: None); c2.vault_fill("#p", "https://account.acompio.com/s")
check("C1 --item-id given: used as is, no listing", len(rn2.calls) == 1 and rn2.calls[0][rn2.calls[0].index("--item-id") + 1] == "given-id")
rn3 = Runner([(1, "fill=failed reason=item-not-unique")])
c3 = B.Ctx(site, fake_page, nap, runner=rn3, dry_run=False, log=lambda *a: None)
try: c3.vault_fill("#p", "https://account.acompio.com/s"); r = None
except Exception as e: r = str(e)
check("C1 other vault failures are not retried by domain", len(rn3.calls) == 1 and r and "item-not-unique" in r)
rn4 = Runner([(1, "fill=failed reason=not-found"), (0, json.dumps({"items": []}))])
c4 = B.Ctx(site, fake_page, nap, runner=rn4, dry_run=False, log=lambda *a: None)
try: c4.vault_fill("#p", "https://account.acompio.com/s"); r = None
except Exception as e: r = str(e)
check("C1 no item in the collection -> BuildError names not-found (no workaround)", r and "not-found" in r and len(rn4.calls) == 2, str(r))
js = open(os.path.join(JOB, "vault_resolve.cjs"), encoding="utf-8").read()
check("C1 the lister reads id / name / uris only: no password, username, notes or totp", "password" not in js.lower().replace("no password", "") and "notes" not in js and "totp" not in js and "username" not in js)

# ---- D1 --row lookup across fix_queue, create_rows, create_queue.rows ------------------------------------------------------
q = {"canonical": CANON,
     "fix_queue": [row("fix-hotfrog", "hotfrog.com", "queued", None)],
     "create_rows": [row("create-old", "old.example", "queued", None)],
     "create_queue": {"rows": [row("create-acompio", "acompio.us", "created-unlisted", None), row("create-tupalo", "tupalo.com", "queued", None)]}}
qp = os.path.join(TMP, "lookup.json"); json.dump(q, open(qp, "w"))
def find(rid, dom):
    try: return B.find_row(rid, types.SimpleNamespace(domain=dom), qp)["id"]
    except SystemExit as e: return "EXIT: %s" % e
check("D1 a fix-* id is found (fix_queue)", find("fix-hotfrog", "hotfrog.com") == "fix-hotfrog")
check("D1 a create-* id is found (create_queue.rows): the batch-13 bug", find("create-acompio", "acompio.us") == "create-acompio")
check("D1 a create-* id in the older create_rows is found", find("create-old", "old.example") == "create-old")
check("D1 spec domain acompio.com vs row acompio.us: same Directory, accepted", find("create-acompio", "acompio.com") == "create-acompio")
check("D1 spec tupalo.co vs row tupalo.com: accepted", find("create-tupalo", "tupalo.co") == "create-tupalo")
check("D1 an unknown id still refuses", "not in the queue" in find("create-nope", "x.example"))
check("D1 a row for a different Directory still refuses", "is for acompio.us, not hotfrog.com" in find("create-acompio", "hotfrog.com"))
check("D1 acompio.us is NOT the same Directory as acompio.evil.example", not B.same_directory("acompio.us", "evil.example") and B.same_directory("acompio.us", "www.acompio.com"))
check("D1 parse_rows (portal overlay) is unchanged: still fix_queue + create_rows only", [r["id"] for r in Q.parse_rows(q)] == ["fix-hotfrog", "create-old"] and len(Q.all_rows(q)) == 4)
dup = dict(q, create_queue={"rows": [row("fix-hotfrog", "x.example", "queued", None)]})
try: Q.all_rows(dup); r = None
except Q.QueueError as e: r = str(e)
check("D1 duplicate ids across lists are refused", r and "duplicated" in r)

# ---- E1 listing URL at submit ----------------------------------------------------------------------------------------------
cases = (("bbb.org", "https://www.bbb.org/get-listed/success", "confirmation"),
         ("loc8nearme.com", "https://www.loc8nearme.com/payment.php?uuid=11111111-2222-4333-8444-555555555555", "confirmation"),
         ("getlistedusa.com", "https://getlistedusa.com/submission/", "confirmation"),
         ("discoverourtown.com", "https://www.discoverourtown.com/add/thankyou.php", "confirmation"),
         ("listyourbusiness.us", "https://listyourbusiness.us/account/businesses/4321", "owner"),
         ("hotfrog.com", "https://www.hotfrog.com/company/12345/alder", "listing"))
for d, u, kind in cases:
    c = LC.capture(d, u, "")
    check("E1 %s %s page is kept as %s" % (d, u.split("/")[-1][:24] or "/", kind), c["kind"] == kind and c["listing_url"] == u, str(c))
check("E1 a listing id is read from the page text", LC.capture("acompio.us", "https://x.example/done", "Thank you! Company ID 99887766 created")["listing_id"] == "99887766")
check("E1 a listing id is read from the owner URL", LC.capture("listyourbusiness.us", "https://listyourbusiness.us/account/businesses/4321", "")["listing_id"] == "4321")
check("E1 the uuid in a payment URL is the id", LC.capture("loc8nearme.com", cases[1][1], "")["listing_id"] == "11111111-2222-4333-8444-555555555555")
check("E1 an about:blank / credential URL / non-http URL captures nothing", all(LC.capture("a.example", u, "")["listing_url"] is None for u in ("about:blank", "https://u:p@a.example/x", "javascript:1", "")))
TBL = {"owner.example": (r"^https://owner\.example/account/listings/(?P<id>\d+)", "https://owner.example/biz/{id}")}
c = LC.capture("owner.example", "https://owner.example/account/listings/77", "", table=TBL)
check("E1 a known owner-view pattern builds the PUBLIC url", c["kind"] == "public-from-owner" and c["listing_url"] == "https://owner.example/biz/77", str(c))
check("E1 an unknown owner-view pattern is NOT guessed into a public url", LC.public_url("listyourbusiness.us", "https://listyourbusiness.us/account/businesses/4321") is None)
check("E1 recheck _permalink uses a built public url (known pattern)", (lambda r: (setattr(LC, "OWNER_TO_PUBLIC", TBL), R._permalink(r))[1])(row("r", "owner.example", "submitted", "https://owner.example/account/listings/77")) in ("https://owner.example/biz/77", None))
LC.OWNER_TO_PUBLIC = {}
# record path: captured url reaches record_transition and the queue row
rec = []
def fake_record(client, rid, to, ev, note, **kw): rec.append((rid, to, ev, kw)); return {"errors": []}
r = Q.submit_row(dict(row("create-x", "bbb.org", "needs-human", None), mike_approval={"approved_by": "mike", "at": "2026-10-25", "row_id": "create-x"}, vaultwarden_item="SCC - bbb.org"),
                 lambda i: {"ok": 1}, record=fake_record, live=True, captured_url="https://www.bbb.org/get-listed/success", captured_id="abc123")
check("E1 submit_row passes the captured URL and id to the record step", rec and rec[0][3] == {"listing_url": "https://www.bbb.org/get-listed/success", "listing_id": "abc123"}, str(rec))
rec.clear(); Q.submit_row(dict(row("create-x", "bbb.org", "needs-human", None), mike_approval={"approved_by": "mike", "at": "2026-10-25", "row_id": "create-x"}, vaultwarden_item="v"), lambda i: {"ok": 1}, record=fake_record, live=True)
check("E1 nothing captured -> record called exactly as before (no extra kwargs)", rec and rec[0][3] == {})
line = B.record_live(dict(row("create-x", "bbb.org", "needs-human", None), mike_approval={"approved_by": "mike", "at": "2026-10-25", "row_id": "create-x"}), types.SimpleNamespace(vault_item="v", record="submitted"), record=fake_record,
                     captured={"listing_url": "https://a.example/thankyou", "listing_id": "9"})
check("E1 record_live carries ctx.state['captured'] to the record step", "recorded" in line and rec[-1][3].get("listing_url") == "https://a.example/thankyou", line)

# the real transitions.record_transition stores them on the row
SRC = os.path.join(HERE, "fixtures", "test_queue.json")
class FakePortal:
    def __init__(s): s.snaps = {}
    def latest_snapshot(s, cid): return {"payload": {"found": 0, "directories": []}}
    def upsert_snapshot(s, cid, day, payload): pass
    def call(s, *a, **k): pass
qq = json.load(open(SRC)); rr = qq["fix_queue"][0]; rr["state"] = "queued"
qpath = os.path.join(TMP, "tq.json"); json.dump(qq, open(qpath, "w"))
out = T.record_transition("SCC", rr["id"], "submitted", None, "submitted via build queue", queue_path=qpath, today="2026-10-26", portal=FakePortal(), directories=None,
                          listing_url="https://a.example/thankyou?id=5", listing_id="5-abc")
saved = json.load(open(qpath))["fix_queue"][0]
check("E1 record_transition saves listing_url and listing_id on the queue row, state moved", saved["listing_url"] == "https://a.example/thankyou?id=5" and saved["listing_id"] == "5-abc" and saved["state"] == "submitted", str({k: saved.get(k) for k in ("state", "listing_url", "listing_id")}))
try:
    T.record_transition("SCC", rr["id"], "submitted", None, "again", queue_path=qpath, today="2026-10-26", portal=FakePortal(), listing_url="javascript:alert(1)"); bad = False
except T.TransitionRefused: bad = True
check("E1 a non-http listing_url is refused", bad)

# ---- E2 capture inside a live run (run_site) ----------------------------------------------------------------------------------
class RPage:
    def __init__(s, url, text=""): s.url, s.text = url, text
    def inner_text(s, sel, timeout=0): return s.text
def mk_step(url, text):
    def fn(ctx): ctx.page.url, ctx.page.text = url, text; return "ok"
    return fn
import build_core as BC
steps = [BC.Step("open", "read", mk_step("https://a.example/register", "")), BC.Step("submit", "submit", mk_step("https://a.example/thankyou.php", "Company ID 4455 created"))]
st = BC.Site("a", "a.example", steps, "SCC - a.example")
ctx = B.Ctx(st, RPage("https://a.example/"), nap, dry_run=False, log=lambda *a: None)
res = B.run_site(st, ctx)
check("E2 run_site keeps the confirmation URL and id in ctx.state['captured']", res["ok"] and ctx.state["captured"]["listing_url"] == "https://a.example/thankyou.php" and ctx.state["captured"]["listing_id"] == "4455", str(ctx.state.get("captured")))
ctx = B.Ctx(st, RPage("https://a.example/"), nap, dry_run=True, log=lambda *a: None); B.run_site(st, ctx)
check("E2 a dry run captures nothing", "captured" not in ctx.state)

# ---- F1 the two new Directories read as listings; the add form / homepage do not --------------------------------------------
check("F1 localsolution /b/<city>/<slug> is a permalink, /businesses/new and / are not", L.is_permalink("localsolution.com", "https://www.localsolution.com/b/exampleton-ky/x-y") and not L.is_permalink("localsolution.com", "https://www.localsolution.com/businesses/new") and not L.is_permalink("localsolution.com", "https://www.localsolution.com/"))
check("F1 listyourbusiness /category/<cat>/<state>/<slug> is a permalink, a category page is not", L.is_permalink("listyourbusiness.us", "https://listyourbusiness.us/category/business-and-professional-services/kentucky/x-y") and not L.is_permalink("listyourbusiness.us", "https://listyourbusiness.us/category/business-and-professional-services"))
check("F1 recheck treats /dashboard, /account and /businesses/new as entry pages", all(R._is_entry_page(u) for u in ("https://www.showmelocal.com/dashboard/correct-data.aspx", "https://listyourbusiness.us/account/businesses/4321", "https://www.localsolution.com/businesses/new")))

shutil.rmtree(TMP, ignore_errors=True)
print(("ALL PASS (%d/%d)" if all(ok) else "FAILED (%d/%d)") % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
