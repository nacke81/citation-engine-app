"""Per-write pre-write backup for nm_transitions (kanban t_9cc92bf1). Run: python tests/nm_backup_test.py (CI). No network, no live queue.

  B1 two writes on the same day make two distinct backups, each byte-identical to the queue right before its write
  B2 the reported path is a file this call created (it did not exist before the call), never an earlier backup
  B3 a stale daily .bak-nm-<day> from earlier in the day is not reported and not overwritten
  B4 dry run: backup None, nothing created; a refused move creates no backup
  B5 same-second writes get a collision suffix and never clobber
  B6 mutation: the old `if not exists` reuse (daily file, reported either way) FAILS the B1/B2/B3 checks
"""
import hashlib, json, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "job"))
os.environ["CE_DIRECTORIES_WRITE"] = "0"
import nm_transitions as NM
import shutil

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + ((" [%s]" % d) if d else ""), flush=True)

DAY = "2026-11-14"
def row(rid, state):
    return {"id": rid, "directory": rid + ".example", "kind": "fix", "state": state, "cost": "free", "mike_approval": None, "history": [], "vaultwarden_item": "x"}
def write_q(rows):
    d = tempfile.mkdtemp(); p = os.path.join(d, "nm-fix-queue.json")
    json.dump({"business": "NM fixture", "fix_queue": rows}, open(p, "w")); return p
def raw(p): return open(p, "rb").read()
def baks(p): return sorted(f for f in os.listdir(os.path.dirname(p)) if ".bak-nm-" in f)
def rec(p, rid, to, **kw): return NM.record_transition("NM", rid, to, None, "note", queue_path=p, today=DAY, **kw)

def scenario():
    """-> list of (name, bool). Two same-day writes plus a stale daily file from earlier in the day."""
    res = []
    p = write_q([row("nm-fix-a", "queued"), row("nm-fix-b", "queued")])
    stale = p + ".bak-nm-" + DAY
    open(stale, "wb").write(b'{"stale": "08:33 state"}')
    stale_bytes = raw(stale)
    pre1 = raw(p); before1 = set(os.listdir(os.path.dirname(p)))
    r1 = rec(p, "nm-fix-a", "skipped")
    pre2 = raw(p); before2 = set(os.listdir(os.path.dirname(p)))
    r2 = rec(p, "nm-fix-b", "skipped")
    b1, b2 = r1["backup"], r2["backup"]
    res.append(("B1 two same-day writes: two distinct backups", bool(b1) and bool(b2) and b1 != b2))
    res.append(("B1 backup 1 byte-identical to the queue right before write 1", bool(b1) and os.path.exists(b1) and raw(b1) == pre1))
    res.append(("B1 backup 2 byte-identical to the queue right before write 2", bool(b2) and os.path.exists(b2) and raw(b2) == pre2 and raw(b2) != pre1))
    res.append(("B2 reported path 1 was created by call 1", bool(b1) and os.path.basename(b1) not in before1 and os.path.exists(b1)))
    res.append(("B2 reported path 2 was created by call 2", bool(b2) and os.path.basename(b2) not in before2 and os.path.exists(b2)))
    res.append(("B3 stale daily file not reported", stale not in (b1, b2)))
    res.append(("B3 stale daily file not overwritten", raw(stale) == stale_bytes))
    return res

def mutant(path, day):   # the defect: daily file, copied only if absent, reported either way
    backup = "%s.bak-nm-%s" % (path, day)
    if not os.path.exists(backup): shutil.copyfile(path, backup)
    return backup

for n, c in scenario(): check(n, c)

# B3b with no stale file the daily file is still kept (other tools read it)
p = write_q([row("nm-fix-a", "queued")]); r = rec(p, "nm-fix-a", "skipped")
check("B3 daily .bak-nm-<day> still created on first write of the day", os.path.exists(p + ".bak-nm-" + DAY))
check("B3 reported backup is the per-write file, not the daily one", r["backup"] != p + ".bak-nm-" + DAY and raw(r["backup"]) == raw(p + ".bak-nm-" + DAY))

# B4
p = write_q([row("nm-fix-a", "queued"), row("nm-fix-l", "live")]); h = raw(p)
r = rec(p, "nm-fix-a", "skipped", dry_run=True)
check("B4 dry run backup None and nothing created", r["backup"] is None and baks(p) == [] and raw(p) == h)
try: rec(p, "nm-fix-l", "skipped"); refused = False
except Exception: refused = True
check("B4 refused move creates no backup", refused and baks(p) == [] and raw(p) == h)

# B5 same second collision: freeze the clock
import datetime as _dt
class FrozenDT(_dt.datetime):
    @classmethod
    def now(cls, tz=None): return cls(2026, 11, 14, 9, 42, 0)
real = NM.datetime.datetime
NM.datetime.datetime = FrozenDT
try:
    p = write_q([row("nm-fix-a", "queued"), row("nm-fix-b", "queued"), row("nm-fix-c", "queued")])
    pres, outs = [], []
    for rid in ("nm-fix-a", "nm-fix-b", "nm-fix-c"):
        pres.append(raw(p)); outs.append(rec(p, rid, "skipped")["backup"])
finally:
    NM.datetime.datetime = real
check("B5 same-second writes: three distinct backups", len(set(outs)) == 3)
check("B5 each is the pre-write content", all(raw(o) == pre for o, pre in zip(outs, pres)))
check("B5 first is the plain stamp, later ones carry a suffix", outs[0].endswith(".bak-nm-20261114-094200") and outs[1].endswith("-1") and outs[2].endswith("-2"))

# B6 mutation must fail the scenario
real_fn = NM.backup_before_write
NM.backup_before_write = mutant
try: mres = scenario()
finally: NM.backup_before_write = real_fn
check("B6 mutant (`if not exists` reuse) fails at least one scenario check", not all(c for _, c in mres), "failed: %s" % [n for n, c in mres if not c])
check("B6 the real implementation passes the same scenario", all(c for _, c in scenario()))

print("%d/%d passed" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
