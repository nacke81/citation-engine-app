"""Catalog helper + migration 004 tests. No network: fake db."""
import os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "job"))
import catalog as C
import directories as D

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

class FakeDB:
    owner = "o"
    def __init__(self): self.calls = []
    def call(self, m, p, b=None, prefer=None): self.calls.append((m, p, b))

db = FakeDB()
b = C.write_cost(db, "showmelocal.com", 6.99, "one-time", "claim fee", "2026-10-25")
check("C1 write_cost PATCHes one domain with cost=paid, amount and period", db.calls[-1][:2] == ("PATCH", "ce_directories?domain=eq.showmelocal.com") and b["cost"] == "paid" and b["cost_amount"] == 6.99 and b["cost_period"] == "one-time")
b = C.write_cost(db, "neustarlocaleze.biz", 99, "/yr", None, "2026-10-25")
check("C1 yearly price", b["cost_period"] == "/yr" and "cost_note" not in b)
b = C.write_cost(db, "mapquest.com", None, None, "price not shown", "2026-10-25")
check("C1 unknown price allowed with null amount/period", b["cost_amount"] is None and b["cost_period"] is None)
def raises(f, *a):
    try: f(*a)
    except C.CatalogError: return True
    return False
n = len(db.calls)
check("C2 bad period refused, no call", raises(C.write_cost, db, "a.com", 5, "weekly") and len(db.calls) == n)
check("C2 negative amount refused", raises(C.write_cost, db, "a.com", -1, "/mo"))
check("C2 non-domain refused (no url, no query injection)", raises(C.write_cost, db, "a.com?x=1", 5, "/mo") and raises(C.write_cost, db, "https://a.com", 5, "/mo"))
b = C.mark_dead(db, "whatsnearby.com", "Bad Catalog row: DNS does not resolve", "2026-10-25")
check("C3 mark_dead sets dead + reason + date, never DELETE", b["dead"] is True and b["dead_on"] == "2026-10-25" and db.calls[-1][0] == "PATCH" and all(c[0] != "DELETE" for c in db.calls))
check("C3 mark_dead needs a reason", raises(C.mark_dead, db, "a.com", "  "))
sql = open(os.path.join(ROOT, "db", "004_catalog_flags.sql"), encoding="utf-8").read()
check("C4 migration is additive and idempotent", "drop column" not in sql.lower() and "drop table" not in sql.lower() and sql.count("add column if not exists") == 5)
check("C4 migration only drops the one check constraint it re-creates", sql.lower().count("drop ") == 1 and "drop constraint if exists ce_directory_status_queue_state_check" in sql)
check("C4 migration widens queue_state with found", "'found'" in sql)
check("C4 migration has no secret", not re.search("sb_" + "secret|service" + "_role|e" + "yJ[A-Za-z0-9_-]{30,}", sql))
cols = set(re.findall(r"add column if not exists (\w+)", sql))
body_cols = set(C.write_cost(FakeDB(), "a.com", 1, "/mo", "n", "2026-10-25")) | set(C.mark_dead(FakeDB(), "a.com", "r", "2026-10-25"))
exist = {"cost", "cost_note", "last_verified", "updated_at"}
check("C4 every column the helpers write exists (002 or 004)", body_cols <= cols | exist, sorted(body_cols - cols - exist))
check("C5 helpers make no Directory request", "urlopen" not in open(os.path.join(ROOT, "job", "catalog.py"), encoding="utf-8").read())
check("C5 found is a Directory-sink state", "found" in D.QUEUE_STATES)
print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})"); sys.exit(0 if all(ok) else 1)
