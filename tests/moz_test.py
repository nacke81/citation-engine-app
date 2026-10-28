"""Moz Domain Authority tests (t_295208a6). Run: python tests/moz_test.py (CI). No network: Moz is a fake, the Directory database is an in-memory fake.

  M1 fixture response -> parsed DA (and unscored / error rows)
  M2 no token skips cleanly, no call made, no raise
  M3 cap: 50 rows per calendar month across runs; MOZ_MAX_ROWS lowers but never raises; account quota respected; quota failure fails closed
  M4 order + cadence: no-Moz-value first by priority, then older than 365 days only
  M5 snapshot authority: Moz rows carry DA, worksheet and unchecked rows null, through write_run
  M6 migration shape; request shape; token never printed; no portal seed / Directory traffic; dry run prints domains + count
"""
import copy, datetime, io, json, os, re, sys, tempfile, contextlib
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ["CE_QUEUE"] = os.path.join(HERE, "fixtures", "test_queue.json")
os.environ["CE_RUNS"] = tempfile.mkdtemp(prefix="ce-runs-")
os.environ.pop("MOZ_API_TOKEN", None); os.environ.pop("MOZ_MAX_ROWS", None)
sys.path.insert(0, os.path.join(ROOT, "job")); sys.path.insert(0, HERE)
import moz as M, portal as P, snapshot as SN  # noqa: E402

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

FX = json.load(open(os.path.join(HERE, "fixtures", "moz_directories.json"), encoding="utf-8"))
TODAY = datetime.date(2026, 10, 27)
DIRS = FX["directories"]
TOKEN = "TESTTOKEN-" + "abc123"

def quota_fn(allotted=50, used=0):
    return lambda: {"jsonrpc": "2.0", "id": "x", "result": {"quota": {"path": "api.limits.data.rows", "allotted": allotted, "used": used}}}

class FakeMoz:
    def __init__(self, scores=None): self.calls = []; self.scores = scores or {}
    def __call__(self, domains):
        self.calls.append(list(domains)); return fixture_response(domains, self.scores)

def fixture_response(domains, scores):
    res, errs = [], []
    for d in domains:
        if d in scores and scores[d] is not None:
            res.append({"site_query": {"query": d, "scope": "domain", "original_site_query": {"query": d, "scope": "domain"}}, "site_metrics": {"root_domain": d, "domain_authority": scores[d]}})
        else:
            errs.append({"site_query": {"query": d, "scope": "domain", "original_site_query": {"query": d, "scope": "domain"}}, "error": {"code": 1, "status": 404}})
    return {"jsonrpc": "2.0", "id": "x", "result": {"results_by_site": res, "errors_by_site": errs}}

class FakeDB:
    def __init__(self, dirs): self.dirs = {d["domain"]: dict(d) for d in dirs}; self.calls = []
    def call(self, method, path, body=None, prefer=None):
        self.calls.append((method, path))
        if method == "GET": return [dict(v) for v in self.dirs.values()]
        if method == "PATCH": self.dirs[path.split("eq.")[1]].update(body)

# M1 parse
resp = json.load(open(os.path.join(HERE, "fixtures", "moz_response.json"), encoding="utf-8"))
got, failed = M.parse_metrics(resp)
check("M1 fixture response -> DA per root domain", got == {"bing.com": 93, "yelp.com": 94, "manta.com": 62}, json.dumps(got))
check("M1 unscored domain (error entry, null DA) is reported, not guessed", sorted(failed) == ["newdir.example", "nulldir.example"], str(failed))
check("M1 out-of-range / non-number DA is no value", M.parse_metrics({"result": {"results_by_site": [{"site_query": {"query": "a.com"}, "site_metrics": {"domain_authority": 250}}, {"site_query": {"query": "b.com"}, "site_metrics": {"domain_authority": "90"}}], "errors_by_site": []}}) == ({}, ["a.com", "b.com"]))
check("M1 www. and scheme are normalized", M.norm("https://www.Bing.com/x") == "bing.com")
check("M1 quota response parsed", M.parse_quota(quota_fn(50, 12)()) == (50, 12))
try: M.parse_metrics({"error": {"code": -32652}}); raised = False
except M.MozError: raised = True
check("M1 an error response raises MozError (no partial write)", raised)

# M2 no token
mz = FakeMoz(); db = FakeDB(DIRS)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rep = M.run(db=db, today=TODAY, env={}, quota=quota_fn(), fetch=mz)
check("M2 missing token: skipped, no Moz call, no database write", rep["skipped"] and not mz.calls and not [c for c in db.calls if c[0] != "GET"] and rep["reason"] == "no MOZ_API_TOKEN")
check("M2 exactly one log line", buf.getvalue().strip().count("\n") == 0 and "MOZ_API_TOKEN" in buf.getvalue(), buf.getvalue().strip())
with contextlib.redirect_stdout(io.StringIO()):
    r2 = M.refresh(DIRS, TODAY, {}, quota_fn(), mz)
check("M2 refresh() without token skips cleanly too", r2["skipped"] and not mz.calls)

# M3 cap
ENV = {M.TOKEN_ENV: TOKEN}
many = [{"domain": "d%03d.example" % i, "priority": 3, "da": None, "da_checked_on": None} for i in range(120)]
mz = FakeMoz({d["domain"]: 40 for d in many})
with contextlib.redirect_stdout(io.StringIO()):
    r = M.refresh(many, TODAY, ENV, quota_fn(), mz)
check("M3 default cap is 50 rows in ONE batched call", r["rows"] == 50 and len(mz.calls) == 1 and len(mz.calls[0]) == 50, str(r["rows"]))
mz = FakeMoz()
with contextlib.redirect_stdout(io.StringIO()):
    r = M.refresh(many, TODAY, dict(ENV, MOZ_MAX_ROWS="500"), quota_fn(), mz)
check("M3 MOZ_MAX_ROWS=500 still stops at 50", r["rows"] == 50)
with contextlib.redirect_stdout(io.StringIO()):
    r = M.refresh(many, TODAY, dict(ENV, MOZ_MAX_ROWS="7"), quota_fn(), FakeMoz())
check("M3 MOZ_MAX_ROWS=7 lowers it", r["rows"] == 7)
used = [dict(d, da_checked_on="2026-10-03") if i < 45 else d for i, d in enumerate(many)]
mz = FakeMoz()
with contextlib.redirect_stdout(io.StringIO()):
    r = M.refresh(used, TODAY, ENV, quota_fn(50, 0), mz)
check("M3 45 rows already used this calendar month -> only 5 left", r["rows"] == 5 and M.used_this_month(used, TODAY) == 45, str(r["rows"]))
mz = FakeMoz()
with contextlib.redirect_stdout(io.StringIO()):
    r = M.refresh(many[:60] + [dict(d, da_checked_on="2026-10-03") for d in many[60:110]], TODAY, ENV, quota_fn(50, 0), mz)
check("M3 50 rows used this month -> nothing fetched, no call", r["rows"] == 0 and not mz.calls)
mz = FakeMoz()
with contextlib.redirect_stdout(io.StringIO()):
    r = M.refresh(many, TODAY, ENV, quota_fn(50, 48), mz)
check("M3 Moz account says 48 of 50 used -> 2 rows (account count wins)", r["rows"] == 2)
def bad_quota(): raise M.MozError("down")
mz = FakeMoz()
with contextlib.redirect_stdout(io.StringIO()):
    r = M.refresh(many, TODAY, ENV, bad_quota, mz)
check("M3 quota lookup fails -> fail closed, nothing fetched", r["skipped"] and not mz.calls)
with contextlib.redirect_stdout(io.StringIO()):
    r = M.refresh(many, datetime.date(2026, 11, 2), ENV, quota_fn(), FakeMoz())
check("M3 next calendar month the 50 come back", r["rows"] == 50)
check("M3 bad MOZ_MAX_ROWS falls back to 50, negative to 0", M.row_cap({"MOZ_MAX_ROWS": "abc"}) == 50 and M.row_cap({"MOZ_MAX_ROWS": "-4"}) == 0)

# M4 order + cadence
dirs4 = [
    {"domain": "p1-old.example", "priority": 1, "da": 80, "da_source": "worksheet", "da_checked_on": None},
    {"domain": "p4-new.example", "priority": 4, "da": None, "da_checked_on": None},
    {"domain": "p2-new.example", "priority": 2, "da": None, "da_checked_on": None},
    {"domain": "p2-ws.example", "priority": 2, "da": 55, "da_source": "worksheet", "da_checked_on": None},
    {"domain": "stale-400.example", "priority": 1, "da": 70, "da_source": "moz", "da_checked_on": "2025-09-20"},
    {"domain": "stale-900.example", "priority": 1, "da": 70, "da_source": "moz", "da_checked_on": "2024-04-01"},
    {"domain": "fresh-364.example", "priority": 1, "da": 70, "da_source": "moz", "da_checked_on": "2025-10-28"},
    {"domain": "edge-365.example", "priority": 1, "da": 70, "da_source": "moz", "da_checked_on": "2025-10-27"},
    {"domain": "dead.example", "priority": 1, "da": None, "da_checked_on": None, "dead": True},
]
sel = M.select_domains(dirs4, TODAY, 50)
check("M4 no-Moz-value rows first, priority asc (worksheet-only rows count as no Moz value)",
      sel[:4] == ["p1-old.example", "p2-ws.example", "p2-new.example", "p4-new.example"], str(sel))
check("M4 then only rows older than 365 days, oldest first", sel[4:] == ["stale-900.example", "stale-400.example"], str(sel))
check("M4 364 and 365 days old are not due; dead rows skipped", "fresh-364.example" not in sel and "edge-365.example" not in sel and "dead.example" not in sel)
check("M4 a short allowance keeps the order", M.select_domains(dirs4, TODAY, 2) == ["p1-old.example", "p2-ws.example"])
mz = FakeMoz({"p1-old.example": 91, "p2-ws.example": None})
with contextlib.redirect_stdout(io.StringIO()):
    r = M.refresh(dirs4[:4], TODAY, ENV, quota_fn(), mz)
up = dict(r["updates"])
check("M4 a scored domain writes da + da_source moz + checked date", up["p1-old.example"] == {"da": 91, "da_source": "moz", "da_checked_on": "2026-10-27"})
check("M4 an unscored domain is stamped checked but keeps its worksheet da and source (not shown as Moz)", up["p2-ws.example"] == {"da_checked_on": "2026-10-27"})
db = FakeDB(dirs4[:4])
with contextlib.redirect_stdout(io.StringIO()):
    M.run(db=db, today=TODAY, env=ENV, quota=quota_fn(), fetch=FakeMoz({"p1-old.example": 91}))
check("M4 run() PATCHes only ce_directories rows, one per fetched domain", all(c[1].startswith("ce_directories") for c in db.calls) and sum(1 for c in db.calls if c[0] == "PATCH") == 4 and db.dirs["p1-old.example"]["da_source"] == "moz")
with contextlib.redirect_stdout(io.StringIO()):
    r2 = M.refresh([dict(d, **db.dirs[d["domain"]]) for d in dirs4[:4]], TODAY, ENV, quota_fn(), FakeMoz())
check("M4 a second run the same month fetches nothing (all stamped)", r2["rows"] == 0)
class Boom:
    def call(self, *a, **k): raise RuntimeError("db down " + TOKEN)
with contextlib.redirect_stdout(io.StringIO()) as o:
    rr = M.run(db=Boom(), today=TODAY, env=ENV, quota=quota_fn(), fetch=FakeMoz())
check("M4 run() never raises and never prints the token", rr["skipped"] and TOKEN not in o.getvalue())

# M4b token resolved from an env file (weekly.cmd loads no env file; os.environ has no token)
_td = tempfile.mkdtemp()
_f1, _f2, _missing = os.path.join(_td, "a.env"), os.path.join(_td, "b.env"), os.path.join(_td, "none.env")
open(_f1, "w", encoding="utf-8").write("# c\nOTHER=1\nMOZ_API_TOKEN=\"" + TOKEN + "\"\n")
open(_f2, "w", encoding="utf-8").write("MOZ_API_TOKEN=second-file-value\n")
seen = {}
def spy_transport(token):
    seen["token"] = token
    return quota_fn(), FakeMoz({"p1-old.example": 91})
_real_lt = M.live_transport
M.live_transport = spy_transport
mz = None
try:
    db = FakeDB(dirs4[:4])
    with contextlib.redirect_stdout(io.StringIO()) as o:
        rr = M.run(db=db, today=TODAY, env={}, files=[_missing, _f1, _f2])
finally:
    M.live_transport = _real_lt
check("M4b token only in an env file: run() fetches and writes", not rr["skipped"] and sum(1 for c in db.calls if c[0] == "PATCH") == 4 and db.dirs["p1-old.example"]["da_source"] == "moz")
check("M4b the first file with a value wins, quotes stripped", seen.get("token") == TOKEN)
check("M4b nothing printed contains the token or a file path", TOKEN not in o.getvalue() and "second-file-value" not in o.getvalue() and _td not in o.getvalue(), o.getvalue())
check("M4b os.environ wins over files", M.resolve_token({M.TOKEN_ENV: "envwins"}, [_f1]) == "envwins")
check("M4b explicit env with no files reads no real file", M.resolve_token({}) is None)
check("M4b default file order: hermes/.env then profile .env", [x.replace("\\", "/").split("hermes/", 1)[1] for x in M.env_files()] == [".env", "profiles/citation-engineer/.env"], str(M.env_files()))
# control: no token anywhere
mz = FakeMoz(); db = FakeDB(dirs4[:4])
with contextlib.redirect_stdout(io.StringIO()) as o:
    rc = M.run(db=db, today=TODAY, env={}, quota=quota_fn(), fetch=mz, files=[_missing, _missing + "2"])
check("M4b control: no token anywhere = one skip line, no calls", rc["skipped"] and not mz.calls and not [c for c in db.calls if c[0] != "GET"] and o.getvalue().strip().count("\n") == 0 and "MOZ_API_TOKEN" in o.getvalue())

# M5 snapshot authority
SCC = json.load(open(os.path.join(HERE, "fixtures", "snapshot-scc-2026-10-27.json"), encoding="utf-8"))["payload"]
doms = [d["domain"] for d in SCC["directories"]]
amap = {doms[0]: 93, doms[1]: 62}
out = SN.apply_authority(SCC, amap)
auth = {d["domain"]: d["authority"] for d in out["directories"]}
check("M5 Moz rows carry DA, every other row is null", auth[doms[0]] == 93 and auth[doms[1]] == 62 and all(v is None for k, v in auth.items() if k not in amap) and len(auth) == 86)
check("M5 no map -> all null (a stale worksheet number in the payload is cleared)", all(d["authority"] is None for d in SN.apply_authority(dict(SCC, directories=[dict(d, authority=77) for d in SCC["directories"]]), None)["directories"]))
check("M5 apply_authority does not mutate its input", all(d.get("authority") is None for d in SCC["directories"]) and out is not SCC)
check("M5 summary untouched", out.get("summary") == SCC.get("summary"))
class FakePortal(P.Portal):
    def __init__(self):
        super().__init__("https://portal.example", "SECRETKEY123", opener=self._open); self.store = {}; self.calls = []
    def _open(self, req):
        self.calls.append((req.get_method(), req.full_url))
        body = json.loads(req.data) if req.data else None
        out = b""
        if req.get_method() == "POST":
            for r in body: self.store[(r["client_id"], r["source"], r["captured_day"])] = r
        else:
            out = json.dumps([r for r in self.store.values() if r["client_id"] in req.full_url and r["captured_day"] in req.full_url]).encode()
        class R(io.BytesIO):
            def __enter__(s): return s
            def __exit__(s, *a): return False
        return R(out)

def checks_for(biz):
    names = ["bing.com", "yelp.com", "manta.com"] + ["d%02d.example" % i for i in range(22)]
    return [dict(biz=biz, directory=n, result="absent", url=None, method="m", note=None, diffs=None) for n in names]

def write_with_authority(fp, amap):
    P.write_run(checks_for("SCC") + checks_for("NM"), "2026-10-27", fp, queue_rows=[], authority=amap)

fp = FakePortal()
write_with_authority(fp, {"bing.com": 93})
scc = [r["payload"] for r in fp.store.values() if r["client_id"] == P.ALLOWED["SCC"]][0]
nm = [r["payload"] for r in fp.store.values() if r["client_id"] == P.ALLOWED["NM"]][0]
bing = [d for d in scc["directories"] if d["domain"] == "bing.com"]
check("M5 write_run: bing.com authority 93 in the stored SCC snapshot, all others null", bing and bing[0]["authority"] == 93 and sum(1 for d in scc["directories"] if d["authority"] is not None) == 1)
check("M5 write_run: NM snapshot gets the same rule", all(d["authority"] in (None, 93) for d in nm["directories"]))
fp2 = FakePortal(); write_with_authority(fp2, None)
check("M5 write_run with no Moz map: authority null everywhere (as before this card)", all(d["authority"] is None for r in fp2.store.values() for d in r["payload"]["directories"]))
check("M5 authority survives the finalize recount", SN.finalize(out)["directories"][0]["authority"] == 93)

# M6 shapes
sql = open(os.path.join(ROOT, "db", "007_moz_authority.sql"), encoding="utf-8").read()
check("M6 migration adds da_source + da_checked_on, idempotent", "add column if not exists da_source text" in sql and "add column if not exists da_checked_on date" in sql and "da_source in ('moz', 'worksheet')" in sql)
check("M6 migration backfills worksheet source and blocks a seed re-upsert from overwriting a Moz value", "set da_source = 'worksheet' where da is not null" in sql and "old.da_source = 'moz'" in sql and "before update" in sql)
check("M6 migration carries no secret and no data load", not re.search("sb_" + "secret|service" + "_role|e" + "yJ[A-Za-z0-9_-]{30,}", sql) and "insert into" not in sql)
rq = M.build_request(["a.com"] * 70)
check("M6 request is JSON-RPC data.site.metrics.fetch.multiple, scope domain, 50 per call max", rq["method"] == "data.site.metrics.fetch.multiple" and len(rq["params"]["data"]["site_queries"]) == 50 and all(q["scope"] == "domain" for q in rq["params"]["data"]["site_queries"]))
check("M6 quota request is quota.lookup api.limits.data.rows (uses no quota)", M.quota_request()["method"] == "quota.lookup" and M.quota_request()["params"]["data"]["path"] == "api.limits.data.rows")
src = open(os.path.join(ROOT, "job", "moz.py"), encoding="utf-8").read()
check("M6 token only travels in the x-moz-token header; never in a print/log call", 'headers={"x-moz-token": token' in src and not re.search(r"\b(print|log)\([^)\"]*\btoken\b", src) and ".replace(token," in src)
check("M6 moz.py imports no portal / buildqueue / listing / playbook module (no portal seed, no Directory action)", not re.search(r"^\s*(import|from)\s+.*\b(portal|buildqueue|listing|playbooks|recheck|transitions)\b", src, re.M))
check("M6 moz.py only host is api.moz.com", set(re.findall(r"https?://([a-z0-9.\-]+)", src)) == {"api.moz.com"}, str(set(re.findall(r"https?://([a-z0-9.\-]+)", src))))
buf = io.StringIO()
rep = M.dry_run(os.path.join(HERE, "fixtures", "moz_directories.json"), out=lambda s: buf.write(s + "\n"))
txt = buf.getvalue()
check("M6 dry run prints the domains it would fetch and the row count, no network", "would fetch" in txt and ("MOZ DRY RUN rows=%d" % rep["rows"]) in txt and rep["rows"] > 0, txt.splitlines()[-1])
sys.path.insert(0, os.path.join(ROOT, "job")); import run as R  # noqa: E402
check("M6 weekly run wires moz_step before the second portal write; portal_publish reads the Moz map", "moz_step()" in open(os.path.join(ROOT, "job", "run.py"), encoding="utf-8").read() and R.moz_authority(object()) is None)

import urllib.request  # noqa: E402
ua_reqs = []
class _Resp:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return b'{"result": {}}'
_real_urlopen = urllib.request.urlopen
urllib.request.urlopen = lambda req, timeout=None: (ua_reqs.append(req), _Resp())[1]
try:
    M._post(TOKEN, M.quota_request())
finally:
    urllib.request.urlopen = _real_urlopen
ua = ua_reqs[0].get_header("User-agent") if ua_reqs else None
check("M7 _post sends the fixed citation-engine User-Agent, not the urllib default (Cloudflare 1010)", ua == M.USER_AGENT == "citation-engine/1.0 (+h" + "ttps://nack" + "emedia.com)" and "urllib" not in (ua or ""), str(ua))
check("M7 _post still carries the token only in x-moz-token", ua_reqs and ua_reqs[0].get_header("X-moz-token") == TOKEN and TOKEN not in str(ua))

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
