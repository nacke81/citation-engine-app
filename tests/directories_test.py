"""Directory database tests. Run: python tests/directories_test.py (CI). No network: the database is an in-memory fake.

  D1 seed: exactly 148 unique Directories (86 v1 + 62 hunt, t_ab039aed), the weekly 25 all inside, the four 10/21 blockers, Bing = agency account, no client NAP
  D2 migration: generated SQL carries the 86 v1 rows, RLS + force RLS, view is security_invoker, no secret
  D3 weekly sync: check results, claim_status, queue state, create-discovery verdicts land as status rows (SCC + NM)
  D4 transitions: a transition writes queue state; needs-human marks the Directory agent-blocked with the note
  D5 the create-row bug: transitions.py finds rows under create_queue.rows and create_rows as well as fix_queue
"""
import copy, json, os, re, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ.pop("CE_ACTIVITIES_WRITE", None)
sys.path.insert(0, os.path.join(ROOT, "job"))
import cfg
import directories as D
import portal as P
import transitions as T

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

class FakeDB:
    owner = "00000000-0000-0000-0000-000000000001"
    def __init__(self, dirs=None):
        self.calls, self.status, self.dirs = [], {}, dirs or {}
    def call(self, method, path, body=None, prefer=None):
        self.calls.append((method, path, body))
        if method == "POST" and path.startswith("ce_directory_status"):
            for r in body:
                k = (r["owner"], r["biz"], r["directory"]); self.status.setdefault(k, {}).update(r)
        elif method == "GET" and path.startswith("ce_directories"):
            return [dict(domain=d, **v) for d, v in self.dirs.items()]
        elif method == "PATCH":
            d = path.split("eq.")[1]; self.dirs.setdefault(d, {}).update(body)
        return None
    def st(self, biz, d): return self.status.get((self.owner, biz, d), {})

SEED = json.load(open(os.path.join(ROOT, "db", "directories_seed.json"), encoding="utf-8"))
by = {r["domain"]: r for r in SEED}
HUNT = [r for r in SEED if str(r["cut"]).startswith(("cycle1-", "cycle2-"))]
V1 = [r for r in SEED if r not in HUNT]

# D1 seed
check("D1 seed count is 148 unique domains (86 v1 + 59 cycle 1 + 3 cycle 2)", len(SEED) == 148 and len(by) == 148 and len(V1) == 86 and len(HUNT) == 62
      and sum(r["cut"].startswith("cycle1-") for r in HUNT) == 59 and sum(r["cut"].startswith("cycle2-") for r in HUNT) == 3, (len(SEED), len(by)))
check("D1 every weekly-25 domain is in the seed and checked weekly", all(d in by and by[d]["checked_weekly"] for d in cfg.DIRS))
import create_discovery as CD
check("D1 the 10 create-discovery domains are in the seed and checked weekly", all(d in by and by[d]["checked_weekly"] for d in CD.CREATE_DIRS))
check("D1 checked weekly = 25 + 10 (no hunt row is checked weekly)", sum(r["checked_weekly"] for r in SEED) == 35 and not any(r["checked_weekly"] for r in HUNT))
check("D1 acompio zero-result marker known, others not", by["acompio.us"]["zero_marker_known"] and not by["citysquares.com"]["zero_marker_known"])
for d, word in (("yellowpages.com", "Cloudflare"), ("superpages.com", "403"), ("acompio.us", "Turnstile"), ("bing.com", "anti-abuse")):
    check("D1 %s seeded agent-blocked (%s)" % (d, word), by[d]["agent_access"] == "blocked" and word in by[d]["agent_blocker"] and by[d]["agent_blocker_seen_on"] == "2026-10-21")
check("D1 Bing build route is the agency account with GBP sync", by["bing.com"]["build_route"] == "agency-account" and "GBP sync" in by["bing.com"]["build_route_note"]
      and "gbp-sync" in by["bing.com"]["verification_methods"])
check("D1 aggregators route to aggregator", all(by[d]["build_route"] == "aggregator" for d in ("data-axle.com", "neustarlocaleze.biz", "foursquare.com")))
check("D1 claim markers verified for the six claim_rules Directories", {d for d, r in by.items() if r["claim_markers_verified"]} == set(__import__("claim_rules").RULES))
CATS = ("general", "aggregator", "niche-senior", "niche-other", "local", "health-senior-care", "home-services", "legal", "local-regional", "restaurant")
check("D1 enums are valid", all(r["category"] in CATS and r["cost"] in ("free", "paid", "unknown")
      and r["build_route"] in ("agent", "agency-account", "aggregator", "none") and r["agent_access"] in ("ok", "blocked", "unknown") for r in SEED))
blob = json.dumps(SEED)
ident = json.load(open(os.environ["CE_IDENTITY"]))
nap = [v for b in ("SCC", "NM") for k in ("name", "short", "street", "slug") for v in [ident["BIZ"][b][k]]] + [p for b in ("SCC", "NM") for p in ident["BIZ"][b]["phones"]]
check("D1 seed holds no business name, street, slug or phone (templates only)", not any(v.lower() in blob.lower() for v in nap))
check("D1 search templates are placeholders", "{name}" in by["yelp.com"]["search_url_template"] and "{city}" in by["yelp.com"]["search_url_template"])

# D2 migration
sql = open(os.path.join(ROOT, "db", "002_directories.sql"), encoding="utf-8").read()
m = re.search(r"\$seed\$(.*?)\$seed\$", sql, re.S)
check("D2 migration 002 seed equals the 86 v1 rows of directories_seed.json (hunt rows ship in 008)", m and json.loads(m.group(1)) == V1)
check("D2 RLS enabled and forced on both tables, anon revoked", "enable row level security" in sql and "force row level security" in sql and "revoke all on public.%I from anon" in sql
      and "'ce_directories', 'ce_directory_status'" in sql)
check("D2 status policy is owner-scoped, directory policy is read-only", 'on public.ce_directory_status for select to authenticated using (owner = auth.uid())' in sql
      and "for insert" not in sql and "for update" not in sql and "for delete" not in sql)
check("D2 view is security_invoker with a row per Directory x business", "security_invoker = true" in sql and "('SCC'), ('NM')" in sql)
check("D2 migration is idempotent (if not exists / on conflict / create or replace)", "create table if not exists public.ce_directories" in sql and "on conflict (domain)" in sql and "create or replace view" in sql)
check("D2 re-seed never overwrites live access state", not re.search(r"on conflict \(domain\) do update set.*agent_access = excluded", sql, re.S))
check("D2 no secret in migration", not re.search("sb_" + "secret|service" + "_role|e" + "yJ[A-Za-z0-9_-]{30,}", sql))

# D3 weekly sync
DAY = "2026-10-21"
checks = [
    dict(biz="SCC", directory="mapquest.com", result="found", url="https://www.mapquest.com/us/kentucky/x-1", match=True, note="", _claim={"claim_status": "unclaimed", "claim_evidence": {"text": "Own this business? / Claim it"}}),
    dict(biz="NM", directory="mapquest.com", result="absent", url=None, match=None, note=None),
    dict(biz="SCC", directory="yellowpages.com", result="couldnt_check", url=None, match=None, note="blocked"),
    dict(biz="NM", directory="yellowpages.com", result="couldnt_check", url=None, match=None, note="blocked"),
    dict(biz="SCC", directory="yelp.com", result="found", url="https://www.yelp.com/biz/x", match=False, note="stale phone shown", _claim={"claim_status": "unknown", "claim_evidence": None}),
    dict(biz="FAKE", directory="yelp.com", result="absent"),
]
queue = {"fix_queue": [{"id": "fix-a", "directory": "yelp.com", "state": "needs-human", "history": [{"at": "2026-10-20", "from": "queued", "to": "needs-human", "note": "Yelp wants a phone code"}]}],
         "create_queue": {"rows": [{"id": "create-acompio", "directory": "acompio.us", "state": "queued", "found_on": "2026-10-19"}],
                          "last_seen": {"acompio.us": {"state": "absent", "why": "zero results; control found", "on": "2026-10-19"},
                                        "botw.org": {"state": "couldnt", "why": "Cloudflare wall", "on": "2026-10-19"}}}}
db = FakeDB(dirs={"mapquest.com": {"agent_access": "unknown"}, "yellowpages.com": {"agent_access": "blocked", "agent_blocker_source": "manual"}, "yelp.com": {"agent_access": "unknown"}})
res = D.sync_run(checks, DAY, queue=queue, db=db)
check("D3 SCC found row: result, url, match, claim_status", (lambda s: s["last_result"] == "found" and s["last_url"].endswith("x-1") and s["last_match"] is True and s["claim_status"] == "unclaimed" and s["claim_evidence_text"])(db.st("SCC", "mapquest.com")))
check("D3 NM row written too, result absent, claim null", db.st("NM", "mapquest.com").get("last_result") == "absent" and db.st("NM", "mapquest.com").get("claim_status") is None)
check("D3 walled search is couldn't check with its reason", db.st("SCC", "yellowpages.com").get("last_result") == "couldnt_check" and db.st("SCC", "yellowpages.com").get("last_note") == "blocked")
check("D3 FAKE business is never written", not any(k[1] == "FAKE" for k in db.status))
check("D3 queue state + blocker note land on the status row", (lambda s: s["queue_state"] == "needs-human" and s["queue_note"] == "Yelp wants a phone code" and s["queue_row_id"] == "fix-a" and s["queue_kind"] == "fix")(db.st("SCC", "yelp.com")))
check("D3 queue merge keeps the check columns of the same row", db.st("SCC", "yelp.com").get("last_result") == "found" and db.st("SCC", "yelp.com").get("last_note") == "stale phone shown")
check("D3 create_queue.rows state lands as a create row", (lambda s: s["queue_state"] == "queued" and s["queue_kind"] == "create")(db.st("SCC", "acompio.us")))
check("D3 create-discovery verdicts fill last_result (absent / couldn't check)", db.st("SCC", "acompio.us").get("last_result") == "absent" and db.st("SCC", "botw.org").get("last_result") == "couldnt_check")
check("D3 a hand-seen blocker is not cleared by a weekly search", db.dirs["yellowpages.com"]["agent_access"] == "blocked")
check("D3 clean first check moves unknown access to ok", db.dirs["mapquest.com"]["agent_access"] == "ok")
check("D3 summary counts", res["checks"] == 5 - 0 and res["queue_rows"] == 2, res)
db2 = FakeDB(dirs={"hotfrog.com": {"agent_access": "unknown"}})
D.sync_run([dict(biz="SCC", directory="hotfrog.com", result="couldnt_check", note="blocked"), dict(biz="NM", directory="hotfrog.com", result="couldnt_check", note="blocked")], DAY, db=db2)
check("D3 a walled weekly search marks the Directory blocked (source weekly)", db2.dirs["hotfrog.com"]["agent_access"] == "blocked" and db2.dirs["hotfrog.com"]["agent_blocker_source"] == "weekly")
D.sync_run([dict(biz="SCC", directory="hotfrog.com", result="found", url="https://x/y", match=True, note=""), dict(biz="NM", directory="hotfrog.com", result="absent")], "2026-10-28", db=db2)
check("D3 a later clean check clears a weekly-sourced block", db2.dirs["hotfrog.com"]["agent_access"] == "ok" and db2.dirs["hotfrog.com"]["agent_blocker"] is None)
check("D3 key shapes are uniform per batch (PostgREST)", all(len({tuple(sorted(r)) for r in c[2]}) == 1 for c in db.calls if c[0] == "POST"))

# D4 transitions write the database
TMP = tempfile.mkdtemp()
class FakePortal:
    def __init__(self): self.snaps = {}
    def latest_snapshot(self, cid): return {"payload": copy.deepcopy(self.snaps[cid])} if cid in self.snaps else None
    def upsert_snapshot(self, cid, day, payload): self.snaps[cid] = copy.deepcopy(payload)
    def call(self, *a, **k): pass
SCC = P.ALLOWED["SCC"]
def portal_with(domain):
    fp = FakePortal(); fp.snaps[SCC] = {"found": 1, "directories": [{"name": domain, "domain": domain, "state": "live", "url": None, "urlKind": "search"}]}; return fp
def qfile(q):
    p = os.path.join(TMP, "q%d.json" % len(os.listdir(TMP))); json.dump(q, open(p, "w")); return p
SRC = json.load(open(os.path.join(HERE, "fixtures", "test_queue.json")))
p = qfile(copy.deepcopy(SRC)); fdb = FakeDB()
r = T.record_transition("SCC", "fix-a", "submitted", "https://a.example/l", "n", queue_path=p, today=DAY, portal=portal_with("a.example"), directories=fdb)
check("D4 transition writes queue state to the Directory database", r["directories_written"] and fdb.st("SCC", "a.example").get("queue_state") == "submitted" and fdb.st("SCC", "a.example").get("queue_row_id") == "fix-a" and not r["errors"], r["errors"])
check("D4 a non-blocking transition does not mark the Directory blocked", not any(c[0] == "PATCH" for c in fdb.calls))
p = qfile(copy.deepcopy(SRC)); fdb = FakeDB()
r = T.record_transition("SCC", "fix-a", "needs-human", None, "Signup is behind a CAPTCHA", queue_path=p, today=DAY, portal=portal_with("a.example"), directories=fdb)
check("D4 needs-human stores the reason on the status row", fdb.st("SCC", "a.example").get("queue_state") == "needs-human" and fdb.st("SCC", "a.example").get("queue_note") == "Signup is behind a CAPTCHA")
check("D4 needs-human marks the Directory agent-blocked with the note", fdb.dirs["a.example"]["agent_access"] == "blocked" and fdb.dirs["a.example"]["agent_blocker"] == "Signup is behind a CAPTCHA"
      and fdb.dirs["a.example"]["agent_blocker_source"] == "transition" and r["directories"]["agent_blocked"])
class BoomDB(FakeDB):
    def call(self, *a, **k): raise RuntimeError("db down")
p = qfile(copy.deepcopy(SRC))
r = T.record_transition("SCC", "fix-a", "submitted", None, None, queue_path=p, today=DAY, portal=portal_with("a.example"), directories=BoomDB())
check("D4 a database failure is reported and never loses the queue write", r["directories_written"] is False and any("directories" in e for e in r["errors"]) and json.load(open(p))["fix_queue"][0]["state"] == "submitted")
os.environ["CE_DIRECTORIES_WRITE"] = "0"
p = qfile(copy.deepcopy(SRC)); r = T.record_transition("SCC", "fix-a", "submitted", None, None, queue_path=p, today=DAY, portal=portal_with("a.example"))
os.environ.pop("CE_DIRECTORIES_WRITE")
check("D4 CE_DIRECTORIES_WRITE=0 switches the sink off (no network)", r["directories_written"] is False and not r["errors"], r["errors"])
dr = T.record_transition("SCC", "fix-a", "submitted", None, None, queue_path=qfile(copy.deepcopy(SRC)), today=DAY, dry_run=True)
check("D4 dry run touches no database", "directories_written" not in dr)

# D5 the create-row bug
CROW = {"id": "create-acompio", "directory": "acompio.us", "kind": "create", "state": "queued", "mike_approval": {"approved_by": "mike", "at": "2026-10-20", "row_id": "create-acompio"}}
q = copy.deepcopy(SRC); q["create_queue"] = {"status": "x", "last_seen": {}, "rows": [copy.deepcopy(CROW)]}
p = qfile(q); fdb = FakeDB()
try:
    r = T.record_transition("SCC", "create-acompio", "needs-human", None, "Turnstile CAPTCHA on signup", queue_path=p, today=DAY, portal=portal_with("acompio.us"), directories=fdb); good = True
except Exception as e:
    good = False; r = {}
after = json.load(open(p))
check("D5 create_queue.rows row is found and transitioned", good and r.get("to") == "needs-human" and after["create_queue"]["rows"][0]["state"] == "needs-human", r.get("errors"))
check("D5 the create row keeps mike_approval and gains history", after["create_queue"]["rows"][0]["mike_approval"] == CROW["mike_approval"] and after["create_queue"]["rows"][0]["history"][-1]["note"] == "Turnstile CAPTCHA on signup")
check("D5 the rest of create_queue and fix_queue is untouched", after["create_queue"]["status"] == "x" and after["fix_queue"] == SRC["fix_queue"])
check("D5 create row recorded as kind create in the database", fdb.st("SCC", "acompio.us").get("queue_kind") == "create" and fdb.dirs["acompio.us"]["agent_access"] == "blocked")
q = copy.deepcopy(SRC); q["create_rows"] = [copy.deepcopy(CROW)]; p = qfile(q)
r = T.record_transition("SCC", "create-acompio", "submitted", None, None, queue_path=p, today=DAY, portal=portal_with("acompio.us"), directories=FakeDB())
check("D5 flat create_rows list still works", r["to"] == "submitted" and json.load(open(p))["create_rows"][0]["state"] == "submitted")
q = copy.deepcopy(SRC); q["create_queue"] = {"rows": [copy.deepcopy(CROW)]}; p = qfile(q); b0 = open(p, "rb").read()
try: T.record_transition("SCC", "create-nope", "submitted", None, None, queue_path=p, today=DAY, portal=portal_with("x"), directories=FakeDB()); rf = False
except T.TransitionRefused: rf = open(p, "rb").read() == b0
check("D5 an unknown id is still refused with the file untouched", rf)
check("D5 before the fix this id was unreachable (old lookup keys only)", all(CROW["id"] not in [r.get("id") for r in (q2.get(k) or [])] for q2 in [dict(SRC, create_queue={"rows": [CROW]})] for k in ("fix_queue", "create_rows")))

# D7 drift: the committed migration must be what the generator makes, and every column the job writes must exist in it
sys.path.insert(0, os.path.join(ROOT, "db"))
import gen_directories_seed as G
gen_sql = G.build_sql(V1)
check("D7 committed 002_directories.sql equals template + committed seed, byte for byte", open(os.path.join(ROOT, "db", "002_directories.sql"), encoding="utf-8", newline="").read().replace("\r\n", "\n") == gen_sql.replace("\r\n", "\n"))
check("D7 every seed row carries agent_blocker_source", all("agent_blocker_source" in r for r in SEED))
def table_cols(name):
    body = re.search(r"create table if not exists public\.%s \((.*?)\n\);" % name, sql, re.S).group(1)
    return {ln.split()[0] for ln in body.split("\n") if ln.strip() and ln.split()[0] not in ("unique", "primary", "constraint")}
cols_dir, cols_stat = table_cols("ce_directories"), table_cols("ce_directory_status")
cols_dir |= set(re.findall(r"add column if not exists (\w+)", sql))
seen_dir, seen_stat = set(), set()
fdb7 = FakeDB(dirs={"yelp.com": {"agent_access": "unknown"}})
D.sync_run(checks, DAY, queue=queue, db=fdb7)
D.sync_run([dict(biz="SCC", directory="hotfrog.com", result="couldnt_check", note="blocked"), dict(biz="NM", directory="hotfrog.com", result="couldnt_check", note="blocked")], DAY, db=fdb7)
fdb7t = FakeDB()
D.sync_transition("SCC", {"id": "fix-a", "directory": "a.example"}, "needs-human", "Signup is behind a CAPTCHA", DAY, db=fdb7t)
D.sync_transition("SCC", {"id": "fix-a", "directory": "a.example"}, "submitted", None, DAY, db=fdb7t)
check("D7 transition scan covers the needs-human PATCH", any(c[0] == "PATCH" and c[2].get("agent_blocker_source") == "transition" for c in fdb7t.calls))
for c in db.calls + db2.calls + fdb7.calls + fdb7t.calls:
    if c[0] == "GET":
        seen_dir |= set(re.search(r"select=([\w,]+)", c[1]).group(1).split(","))
    elif c[0] == "PATCH":
        seen_dir |= set(c[2])
    elif c[0] == "POST":
        for r in c[2]: seen_stat |= set(r)
check("D7 job reads and PATCHes only ce_directories columns that the migration creates", seen_dir and "agent_blocker_source" in seen_dir and seen_dir <= cols_dir, sorted(seen_dir - cols_dir))
check("D7 job upserts only ce_directory_status columns that the migration creates", seen_stat and seen_stat <= cols_stat, sorted(seen_stat - cols_stat))
check("D7 migration adds agent_blocker_source for older tables", "add column if not exists agent_blocker_source" in sql)

# D8 hunt catalog rows (t_ab039aed): 148 unique domains, catalog-only, unknown stays unknown, migration 008 carries the same rows
HUNT_ENUM = dict(agent_access=("blocked", "unknown"), build_route=("none",), weekly_scope=("none",))
check("D8 148 unique domains load from the seed and no hunt domain is in the 86", len({r["domain"] for r in SEED}) == 148 and not ({r["domain"] for r in HUNT} & {r["domain"] for r in V1}))
check("D8 every hunt row is catalog-only: build_eligible false, route none, priority 4, scope none, not checked weekly",
      all(r["build_eligible"] is False and r["build_route"] == "none" and r["priority"] == 4 and r["weekly_scope"] == "none" and not r["checked_weekly"] for r in HUNT))
check("D8 no v1 row carries build_eligible false", all(r.get("build_eligible") is not False for r in V1))
check("D8 hunt agent_access is mapped to the enum: 403/429 walls blocked (21), everything else unknown, probe text kept",
      all(r["agent_access"] in ("blocked", "unknown") for r in HUNT) and sum(r["agent_access"] == "blocked" for r in HUNT) == 21
      and all(("Hunt probe access:" in r["notes"]) if r["agent_access"] == "unknown" else r["agent_blocker"] for r in HUNT))
check("D8 unknown stays unknown: cost, account_needed and weekly_checkable are not defaulted", all(r["account_needed"] == "unknown" and r["weekly_checkable"] == "unknown" for r in HUNT)
      and sum(r["cost"] == "unknown" for r in HUNT) == 58 and {r["cost"] for r in HUNT} <= {"free", "paid", "unknown"})
check("D8 vertical equals category on every hunt row, source is kept", all(r["vertical"] == r["category"] and r["source"] for r in HUNT))
check("D8 null signup_url stays null (23 walled rows incl. opentable and linkedin), none invented", sum(r["signup_url"] is None for r in HUNT) == 23 and by["opentable.com"]["signup_url"] is None and by["linkedin.com"]["signup_url"] is None
      and by["smartcustomer.com"]["signup_url"] == "https://biz.smartcustomer.com/register")
sql8 = open(os.path.join(ROOT, "db", "008_hunt_catalog.sql"), encoding="utf-8").read()
sql9 = open(os.path.join(ROOT, "db", "009_hunt_catalog_seed.sql"), encoding="utf-8").read()
m9 = re.search(r"\$seed\$(.*?)\$seed\$", sql9, re.S)
CRLF, LF = chr(13) + chr(10), chr(10)
INS = r"insert\s+into\s+public\.ce_directories"
check("D8 migration 009 seed equals the hunt rows of directories_seed.json", m9 and json.loads(m9.group(1)) == HUNT)
check("D8 committed 009_hunt_catalog_seed.sql equals template + hunt seed, byte for byte", sql9.replace(CRLF, LF) == G.build_hunt_sql(HUNT).replace(CRLF, LF))
check("D8 split: 008 has NO rows (no insert, no $seed$) and 009 has NO DDL (no alter, create, drop)",
      not re.search(INS, sql8, re.I) and "$seed$" not in sql8 and not re.search(r"^\s*(alter|create|drop)\s", sql9, re.I | re.M))
check("D8 hazard gone: with only 008 applied the table gains 0 rows (008 has no insert, 009 is the only row source and every row is build_eligible false)",
      len(re.findall(INS, sql8, re.I)) == 0 and len(re.findall(INS, sql9, re.I)) == 1 and len(json.loads(m9.group(1))) == 62
      and all(r["build_eligible"] is False for r in json.loads(m9.group(1))))
check("D8 order is written in the files: 009 requires 008 and the merge first, 008 names step 3", "REQUIRES 008" in sql9 and "AFTER the app change is merged" in sql9 and "(3) apply 009" in sql8)
check("D8 hunt seed file equals the hunt rows in directories_seed.json", json.load(open(os.path.join(ROOT, "db", "directories_hunt_seed.json"), encoding="utf-8")) == HUNT)
check("D8 008 is additive and idempotent: columns if not exists, build_eligible default true, no drop table, no delete",
      "add column if not exists build_eligible boolean not null default true" in sql8
      and not re.search(r"drop table|delete from|truncate|do update", sql8, re.I) and all("add column if not exists %s" % c in sql8 for c in ("vertical", "weekly_checkable", "source")))
check("D8 009 is idempotent: on conflict do nothing, no delete, no update", "on conflict (domain) do nothing" in sql9 and not re.search(r"drop table|delete from|truncate|do update", sql9, re.I))
check("D8 008 widens the category CHECK with every hunt category and keeps the old five", all("'%s'" % c in sql8.split("check (category in")[1].split(")")[0] for c in CATS))
check("D8 hunt categories exist in the 008 CHECK", {r["category"] for r in HUNT} <= set(CATS))
check("D8 no secret in 008 or 009", not re.search("sb_" + "secret|service" + "_role|e" + "yJ[A-Za-z0-9_-]{30,}", sql8 + sql9))
cols_dir |= set(re.findall(r"add column if not exists (\w+)", sql8))
check("D8 every seed key the 009 insert reads is a column", {k for r in HUNT for k in r} <= cols_dir, sorted({k for r in HUNT for k in r} - cols_dir))

src = open(os.path.join(ROOT, "job", "directories.py"), encoding="utf-8").read()
check("D6 directories.py makes no Directory request (only the Supabase REST host)", src.count("urlopen") == 1 and "/rest/v1/" in src)
shutil.rmtree(TMP, ignore_errors=True)
print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})"); sys.exit(0 if all(ok) else 1)
