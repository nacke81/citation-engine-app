"""t_93ae9b6b: the worker that parks a row writes reason_code. Additive: no code given -> the column is never sent."""
import os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "job"))
import directories as D

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)

class DB:
    owner = "o1"
    def __init__(s): s.calls = []
    def call(s, method, path, body=None, prefer=None): s.calls.append((method, path, body)); return None
def posted(db): return [c[2][0] for c in db.calls if c[0] == "POST" and "ce_directory_status" in c[1]]
ROW = {"id": "create-x", "directory": "x.example"}

d1 = DB(); D.sync_transition("SCC", ROW, "needs-human", "paid-tier, Mike decides", "2026-11-04", kind="create", db=d1, reason_code="paid")
check("R1 needs-human with a code writes reason_code in the same upsert as the queue state", posted(d1)[0].get("reason_code") == "paid" and posted(d1)[0]["queue_state"] == "needs-human")
d2 = DB(); D.sync_transition("SCC", ROW, "needs-human", "note", "2026-11-04", kind="create", db=d2)
check("R2 no code given -> the key is not sent at all (safe before migration 011 is applied)", "reason_code" not in posted(d2)[0])
def refuses(**k):
    try: D.sync_transition("SCC", ROW, k.pop("state", "needs-human"), "n", "2026-11-04", kind="create", db=DB(), **k)
    except D.DirectoriesError: return True
    return False
check("R3 an unknown code is refused", refuses(reason_code="made_up"))
check("R4 a code on any other move is refused", refuses(state="live", reason_code="paid") and refuses(state="queued", reason_code="paid"))
d5 = DB(); D.sync_transition("SCC", ROW, "live", None, "2026-11-04", kind="create", db=d5)
check("R5 a live move never sends reason_code", "reason_code" not in posted(d5)[0])

js = open(os.path.join(ROOT, "site", "reasons.js"), encoding="utf-8").read()
js_codes = set(re.findall(r"^  (\w+): \{ label:", js, re.M))
derived_only = {"blocked_unknown", "no_result", "unsearchable", "other"}   # read from ce_checks / fallback, never stored
check("R6 every stored code is a code the page knows", set(D.REASON_CODES) <= js_codes, str(set(D.REASON_CODES) - js_codes))
check("R7 every page code is either stored or derived-only (the two lists cannot drift)", js_codes - set(D.REASON_CODES) == derived_only, str(js_codes - set(D.REASON_CODES)))

sql = open(os.path.join(ROOT, "db", "011_reason_code.sql"), encoding="utf-8").read()
body = re.sub(r"(?m)^--.*$", "", sql)
check("R8 migration 011 is additive: one nullable column + the view, no drop/delete/update/insert", "add column if not exists reason_code text;" in body and not re.search(r"(?i)\b(drop|delete|update|insert|truncate)\b", body))
check("R9 the view the page reads keeps every earlier column and appends reason_code last", all(c in body for c in ("s.build_action", "s.proof_url", "s.proof_nap_match", "s.queue_note")) and body.rstrip().split("from public.ce_directories")[0].rstrip().endswith("s.reason_code"))
check("R10 the weekly job source never writes reason_code (the check path is untouched)", "reason_code" not in open(os.path.join(ROOT, "job", "run.py"), encoding="utf-8").read())

print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})"); sys.exit(0 if all(ok) else 1)
