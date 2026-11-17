"""NM backup retention + transitions.py park/create use the shared per-write backup (kanban t_13adf93c). Run: python tests/nm_backup_retention_test.py (CI). No network, no live queue.

  R1 55 writes leave exactly NM_BACKUP_KEEP (50) per-write files, the newest 50; the daily file and a planted .bak-t_x file are untouched
  R2 a prune that raises does not fail the write (stderr only); an unremovable file does not either
  R3 the backup the call just reported is never pruned
  P1 park NM twice in one day: two distinct reported backups, each byte-identical to the queue right before its write, each created by that call
  P2 create_row twice: same; dry run keeps backup None and creates nothing
  M1 mutation: transitions.py `if not exists` daily reuse FAILS the P checks
  M2 mutations of the SHIPPED nm_transitions source (regex `$` dropped; `^` dropped + match->search; keep_path skip removed) each FAIL a check
  R1b planted look-alike files (`.keep` suffix, `-pre-t_abc` suffix, another queue's backup), older than every real stamp, survive byte-identical
  R4 50 future-stamped backups + one write: the reported (oldest) backup survives with the pre-write bytes
  W1 transitions.py NM park and create_row each prune to exactly 50 (55 planted); daily + .bak-t_x + look-alikes untouched
"""
import datetime as _dt, json, os, re, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "job"))
os.environ["CE_DIRECTORIES_WRITE"] = "0"
import nm_transitions as NM
import transitions as T
import os as _fo; _fo.environ["CE_PORTAL_ENV"] = _fo.path.join(_fo.path.dirname(_fo.path.abspath(__file__)), "no-such-portal.env")  # t_2ddc7067: fail closed, never the prod portal
import portal as P
import yt_obs as YO
import shutil

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + ((" [%s]" % d) if d else ""), flush=True)

DAY = "2026-11-14"
# only the regex anchors protect these; all older than any real stamp so a loose regex prunes them first
LOOKALIKES = [("@Q.bak-nm-20200101-000000.keep", b"keep"), ("@Q.bak-nm-20200101-000000-pre-t_abc", b"pre"), ("other-@Q.bak-nm-20200101-000000", b"other")]
def look_path(p, suf): return os.path.join(os.path.dirname(p), suf.replace("@Q", os.path.basename(p)))
def row(rid, state="queued"):
    return {"id": rid, "directory": rid.split("nm-fix-")[-1] + ".example", "kind": "fix", "state": state, "cost": "free", "mike_approval": None, "history": [], "vaultwarden_item": "x"}
def write_q(rows):
    d = tempfile.mkdtemp(); p = os.path.join(d, "nm-fix-queue.json")
    json.dump({"business": "NM fixture", "fix_queue": rows}, open(p, "w")); return p
def raw(p): return open(p, "rb").read()
def names(p): return sorted(os.listdir(os.path.dirname(p)))
def perwrite(p): return [n for n in names(p) if re.fullmatch(re.escape(os.path.basename(p)) + r"\.bak-nm-\d{8}-\d{6}(-\d+)?", n)]

class Clock(_dt.datetime):   # every call is one second later: stamps sort in write order
    t = _dt.datetime(2026, 11, 14, 9, 0, 0)
    @classmethod
    def now(cls, tz=None):
        cls.t += _dt.timedelta(seconds=1); return cls(cls.t.year, cls.t.month, cls.t.day, cls.t.hour, cls.t.minute, cls.t.second)
real_dt = NM.datetime.datetime

def fifty_five(prune=None, mod=None):
    mod = mod or NM
    """55 NM writes (flip one row between two states); returns (queue path, list of reported backups, planted bytes)."""
    Clock.t = _dt.datetime(2026, 11, 14, 9, 0, 0)
    p = write_q([row("nm-fix-a")])
    daily = p + ".bak-nm-" + DAY; card = p + ".bak-t_x"
    open(daily, "wb").write(b"daily"); open(card, "wb").write(b"card")
    for suf, body in LOOKALIKES: open(look_path(p, suf), "wb").write(body)
    outs = []
    if prune: NM.prune_backups_real, NM.prune_backups = NM.prune_backups, prune
    NM.datetime.datetime = Clock
    try:
        for i in range(55):
            q = json.load(open(p)); q["fix_queue"][0]["state"] = "queued"; q["fix_queue"][0]["history"] = []; json.dump(q, open(p, "w"))
            outs.append(mod.record_transition("NM", "nm-fix-a", "skipped", None, "n%d" % i, queue_path=p, today=DAY)["backup"])
    finally:
        NM.datetime.datetime = real_dt
        if prune: NM.prune_backups = NM.prune_backups_real
    return p, outs

def r1_checks(p, outs):
    daily = p + ".bak-nm-" + DAY; card = p + ".bak-t_x"
    left = perwrite(p)
    return [("R1 exactly 50 per-write backups after 55 writes", len(left) == NM.NM_BACKUP_KEEP == 50 and len(left) == 50, len(left)),
            ("R1 they are the newest 50 reported backups", left == sorted(os.path.basename(o) for o in outs[-50:])),
            ("R1 daily .bak-nm-<day> untouched", os.path.exists(daily) and raw(daily) == b"daily"),
            ("R1 planted .bak-t_x untouched", os.path.exists(card) and raw(card) == b"card"),
            *[("R1b look-alike %s untouched" % suf.split("bak-nm-")[1], os.path.exists(look_path(p, suf)) and raw(look_path(p, suf)) == body) for suf, body in LOOKALIKES],
            ("R3 the last reported backup still exists", os.path.exists(outs[-1]))]

p, outs = fifty_five()
for n, c, *d in r1_checks(p, outs): check(n, c, *(str(x) for x in d))

# M2 real source mutations: compile the shipped nm_transitions.py with edits into a fresh module; the scenarios must catch each
import types
NM_PATH = os.path.join(HERE, "..", "job", "nm_transitions.py")
NM_SRC = open(NM_PATH, encoding="utf-8").read()
def mutated(*edits):
    src = NM_SRC
    for old, new in edits:
        assert src.count(old) == 1, "mutation target not found exactly once: " + old
        src = src.replace(old, new)
    m = types.ModuleType("nm_transitions_mut"); m.__file__ = NM_PATH
    exec(compile(src, NM_PATH, "exec"), m.__dict__); return m
RX_END = r'(?:-(\d+))?$")'
RX_START = 'r"^" + re.escape(base)'
KEEP_SKIP = "if keep_path and os.path.abspath(f) == os.path.abspath(keep_path): continue"
check("M2 control: unmutated recompiled source passes every R1 check", all(c for _, c, *_d in r1_checks(*fifty_five(mod=mutated()))))
for label, edits in [("M2a regex `$` dropped", [(RX_END, RX_END.replace("$", ""))]),
                     ("M2b regex `^` dropped and match->search", [(RX_START, "re.escape(base)"), ("m = pat.match(name)", "m = pat.search(name)")])]:
    mp, mouts = fifty_five(mod=mutated(*edits))
    bad = [n for n, c, *_d in r1_checks(mp, mouts) if not c]
    check(label + " (shipped source) fails an R1/R1b check", bool(bad), bad)

# R4 never prune the reported backup: 50 future-stamped backups, so this call's own backup sorts oldest
def r4(mod):
    Clock.t = _dt.datetime(2026, 11, 14, 9, 0, 0)
    p = write_q([row("nm-fix-a")])
    for i in range(50): shutil.copyfile(p, "%s.bak-nm-20991231-0000%02d" % (p, i))
    pre = raw(p); NM.datetime.datetime = Clock
    try: out = mod.record_transition("NM", "nm-fix-a", "skipped", None, "n", queue_path=p, today=DAY)
    finally: NM.datetime.datetime = real_dt
    b = out["backup"]
    return [("R4 reported backup is the oldest stamp (scenario valid)", b and os.path.basename(b) < os.path.basename(p) + ".bak-nm-20991231"),
            ("R4 reported backup still exists", bool(b) and os.path.exists(b)),
            ("R4 reported backup holds the pre-write bytes", bool(b) and os.path.exists(b) and raw(b) == pre)]
for n, c in r4(NM): check(n, c)
bad = [n for n, c in r4(mutated((KEEP_SKIP, "pass"))) if not c]
check("M2c keep_path skip removed (shipped source) fails an R4 check", bool(bad), bad)

# R2 a prune that raises does not fail the write
real_prune = NM.prune_backups
def boom(path, keep_path=None, keep=None): raise RuntimeError("boom")
# the guard lives inside prune_backups: simulate its failure points instead (listdir raising, remove raising)
p2 = write_q([row("nm-fix-a"), row("nm-fix-b")])
real_listdir, real_remove = os.listdir, os.remove
def bad_listdir(d): raise OSError("listdir denied")
os.listdir = bad_listdir
try: r = NM.record_transition("NM", "nm-fix-a", "skipped", None, "n", queue_path=p2, today=DAY); e1 = None
except Exception as e: r, e1 = None, e
finally: os.listdir = real_listdir
check("R2 listdir failure in the prune does not fail the write", e1 is None and r and json.load(open(p2))["fix_queue"][0]["state"] == "skipped", e1)
Clock.t = _dt.datetime(2026, 11, 14, 10, 0, 0)
p3, o3 = write_q([row("nm-fix-a")]), []
for i in range(3):   # fill past a cap of 2 with real names, then make remove raise
    shutil.copyfile(p3, "%s.bak-nm-20261114-0%d0000" % (p3, i + 1))
def bad_remove(f): raise PermissionError("locked")
os.remove = bad_remove
try:
    r3 = NM.record_transition("NM", "nm-fix-a", "skipped", None, "n", queue_path=p3, today=DAY); e3 = None
    NM.prune_backups(p3, keep_path=r3["backup"], keep=1)
except Exception as e: r3, e3 = None, e
finally: os.remove = real_remove
check("R2 an unremovable backup does not raise (and the write stands)", e3 is None and r3 and json.load(open(p3))["fix_queue"][0]["state"] == "skipped", e3)

# P1 transitions.record_transition park on NM, twice, same day
class FP:
    def __init__(self): self.calls = []
    def latest_snapshot(self, cid): return {"payload": {"found": 1, "directories": [{"name": "a.example", "domain": "a.example", "state": "live", "url": None, "urlKind": "search"}]}}
    def upsert_snapshot(self, cid, day, payload): pass
    def call(self, method, path, body=None, prefer=None): self.calls.append((method, path, body))
LOCAL = os.path.join(tempfile.mkdtemp(), "allow.json")
def park(p, rid, **kw):
    return T.record_transition("NM", rid, "needs-human", None, "n", queue_path=p, today=DAY, portal=FP(), verify_type="phone-call",
                               observation=YO.obs("phone-call", DAY), reason_code="phone_verify", allowlist_path=LOCAL, vault_item="NM - x login", **kw)

def park_scenario():
    p = write_q([row("nm-fix-a"), row("nm-fix-b")])
    stale = p + ".bak-nm-" + DAY; open(stale, "wb").write(b'{"stale": "morning"}')
    res = []
    pre1, before1 = raw(p), set(names(p)); r1 = park(p, "nm-fix-a")
    pre2, before2 = raw(p), set(names(p)); r2 = park(p, "nm-fix-b")
    b1, b2 = r1.get("backup"), r2.get("backup")
    res.append(("P1 two same-day NM parks: two distinct reported backups", bool(b1) and bool(b2) and b1 != b2))
    res.append(("P1 backup 1 byte-identical to the queue right before park 1", bool(b1) and os.path.exists(b1) and raw(b1) == pre1))
    res.append(("P1 backup 2 byte-identical to the queue right before park 2", bool(b2) and os.path.exists(b2) and raw(b2) == pre2 and pre2 != pre1))
    res.append(("P1 each reported backup was created by its call", bool(b1) and bool(b2) and os.path.basename(b1) not in before1 and os.path.basename(b2) not in before2))
    res.append(("P1 the stale daily file is not reported and not overwritten", stale not in (b1, b2) and raw(stale) == b'{"stale": "morning"}'))
    return res
for n, c in park_scenario(): check(n, c)

# P1b the daily file is still kept (park_any_tenant_test reads it) on a fresh day
p = write_q([row("nm-fix-a")]); r = park(p, "nm-fix-a")
check("P1b daily .bak-nm-<day> still created; reported file is the per-write one", os.path.exists(p + ".bak-nm-" + DAY) and r["backup"] != p + ".bak-nm-" + DAY and re.search(r"\.bak-nm-\d{8}-\d{6}(-\d+)?$", r["backup"]))

# P2 create_row twice + dry run
p = write_q([row("nm-fix-a")]); h = raw(p)
d = T.create_row("NM", "dry.example", "fix", queue_path=p, today=DAY, dry_run=True, directories=None) if False else None
c1 = T.create_row("NM", "one.example", "fix", queue_path=p, today=DAY)
pre2 = raw(p); c2 = T.create_row("NM", "two.example", "fix", queue_path=p, today=DAY)
check("P2 create_row twice: distinct per-write backups, each the pre-write queue", c1["backup"] != c2["backup"] and raw(c1["backup"]) == h and raw(c2["backup"]) == pre2)
p = write_q([row("nm-fix-a")]); h = raw(p)
cd = T.create_row("NM", "dry.example", "fix", queue_path=p, today=DAY, dry_run=True)
check("P2 create_row dry run: backup None, nothing created, queue unchanged", cd["backup"] is None and perwrite(p) == [] and not os.path.exists(p + ".bak-nm-" + DAY) and raw(p) == h)
pp = write_q([row("nm-fix-a")]); hp = raw(pp)
rd = T.record_transition("NM", "nm-fix-a", "needs-human", None, "n", queue_path=pp, today=DAY, portal=FP(), verify_type="phone-call", observation=YO.obs("phone-call", DAY), allowlist_path=LOCAL, vault_item="x", dry_run=True)
check("P2 park dry run: backup None (or absent), nothing created", rd.get("backup") is None and perwrite(pp) == [] and raw(pp) == hp)

# W1 transitions.py writers are bounded: 55 planted per-write backups, then ONE real park / ONE real create_row -> exactly 50 remain
def w1(action):
    p = write_q([row("nm-fix-a")])
    planted = ["%s.bak-nm-20200101-%06d" % (p, i) for i in range(55)]
    for f in planted: open(f, "wb").write(b"old")
    card = p + ".bak-t_x"; open(card, "wb").write(b"card")
    for suf, body in LOOKALIKES: open(look_path(p, suf), "wb").write(body)
    pre = raw(p); out = action(p)
    left = perwrite(p); b = out.get("backup")
    return [("W1 exactly 50 per-write backups remain (55 planted + 1 new)", len(left) == 50, len(left)),
            ("W1 the reported backup is kept and holds the pre-write bytes", bool(b) and os.path.exists(b) and raw(b) == pre),
            ("W1 the 6 oldest planted files are the ones pruned", not any(os.path.exists(f) for f in planted[:6]) and all(os.path.exists(f) for f in planted[6:])),
            ("W1 daily .bak-nm-<day> exists (created by the call) and .bak-t_x untouched", os.path.exists(p + ".bak-nm-" + DAY) and os.path.exists(card) and raw(card) == b"card"),
            ("W1 look-alikes untouched", all(os.path.exists(look_path(p, s)) and raw(look_path(p, s)) == bd for s, bd in LOOKALIKES))]
for name, act in [("park", lambda p: park(p, "nm-fix-a")), ("create_row", lambda p: T.create_row("NM", "new.example", "fix", queue_path=p, today=DAY))]:
    for n, c, *d in w1(act): check(name + " " + n, c, *(str(x) for x in d))

# M1 mutation: the old reuse in transitions.py (shared function replaced by daily copy-if-absent, reported either way)
def old_reuse(path, day):
    b = "%s.bak-nm-%s" % (path, day)
    if not os.path.exists(b): shutil.copyfile(path, b)
    return b
real_fn = NM.backup_before_write
NM.backup_before_write = old_reuse
try: mres = park_scenario()
finally: NM.backup_before_write = real_fn
check("M1 mutant (`if not exists` reuse reached via transitions.py) fails at least one P1 check", not all(c for _, c in mres), [n for n, c in mres if not c])
check("M1 the real implementation passes the same scenario", all(c for _, c in park_scenario()))

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
