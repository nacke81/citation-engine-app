"""Queue tests. Run: python tests/queue_test.py (CI). Q1 overlay, Q2 approval gate, Q3 Vaultwarden fail-closed, Q4 no network, Q5 scope."""
import os, sys, copy
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ["CE_QUEUE"] = os.path.join(HERE, "fixtures", "test_queue.json")
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import buildqueue as Q
import portal as P

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)
def raises(f, E=Exception):
    try: f(); return False
    except E: return True

rows = Q.load_rows()
check("Q1 queue file has the 5 SCC fix rows, all mike_approval null", len(rows) == 5 and all(r["mike_approval"] is None for r in rows))
domains = [r["directory"] for r in rows]
checks = [dict(biz="SCC", directory=d, result="found", url="https://%s/x" % d, method="m", note=None, diffs=[{"field": "name", "live": "a", "canonical": "b"}]) for d in domains] + \
         [dict(biz="SCC", directory="ok%d.example" % i, result="found", url="https://ok/x", method="m", note=None, diffs=[]) for i in range(6)]
base = P.build_payload(checks, "2026-10-19")
ov = Q.overlay_directories(base, rows, "2026-10-19")
st = {d["domain"]: d["state"] for d in ov["directories"]}
check("Q1 the 5 queued rows show needs-human on the portal payload", all(st[d] == "needs-human" for d in domains))
check("Q1 other rows untouched and counts unchanged", all(st["ok%d.example" % i] == "live" for i in range(6)) and all(ov[k] == base[k] for k in ("found", "correct", "withNapErrors", "notFound", "couldntCheck")))
check("Q1 input payload not mutated", all(d["state"] == "live" for d in base["directories"]))
for s in Q.PORTAL_STATES:
    o = Q.overlay_directories(base, [dict(rows[0], state=s)], "2026-10-19")
    check("Q1 state %s maps through" % s, [d for d in o["directories"] if d["domain"] == rows[0]["directory"]][0]["state"] == s)
o = Q.overlay_directories(base, [dict(id="create-x", directory="new.example", state="queued")], "2026-10-19")
check("Q1 create row is appended with state and no url", [d for d in o["directories"] if d["domain"] == "new.example"][0]["state"] == "needs-human" and len(o["directories"]) == len(base["directories"]) + 1)

ov_urls = {d["domain"]: d for d in ov["directories"]}
check("Q1 queued rows with a resolved listing keep url and urlKind listing", all(ov_urls[d]["url"] == "https://%s/x" % d and ov_urls[d]["urlKind"] == "listing" for d in domains), str([(d, ov_urls[d]["url"], ov_urls[d]["urlKind"]) for d in domains]))
sr = copy.deepcopy(base)
sr["directories"][[d["domain"] for d in sr["directories"]].index(domains[0])].update(url=None, urlKind="search")
o = Q.overlay_directories(sr, rows, "2026-10-19")
o0 = [d for d in o["directories"] if d["domain"] == domains[0]][0]
check("Q1 queued row with no permalink stays url null, urlKind search", o0["url"] is None and o0["urlKind"] == "search")

# Exercise the production writer boundary without any outbound calls.
class CapturePortal:
    def __init__(self):
        self.writes = {}
    def upsert_snapshot(self, client_id, captured_day, payload):
        self.writes[client_id] = copy.deepcopy(payload)
        return {"client_id": client_id, "source": P.SOURCE, "captured_day": captured_day}

nm_checks = [dict(c, biz="NM") for c in checks]
capture = CapturePortal()
P.write_run(checks + nm_checks, "2026-10-19", capture)
scc_payload = capture.writes[P.ALLOWED["SCC"]]
check("Q1 write_run loads queue and publishes all 5 needs-human states",
      all(d["state"] == "needs-human" for d in scc_payload["directories"] if d["domain"] in domains)
      and sum(d["domain"] in domains for d in scc_payload["directories"]) == 5)
check("Q1 write_run leaves NM payload unchanged", capture.writes[P.ALLOWED["NM"]] == P.build_payload(nm_checks, "2026-10-19"))
check("Q1 write_run preserves SCC metrics and has no BrightLocal score",
      all(scc_payload[k] == base[k] for k in base if k != "directories") and scc_payload["keyScore"] is None)

login = lambda item: {"user": "u", "pw": "p"}
r0 = copy.deepcopy(rows[0]); r0["vaultwarden_item"] = "SCC Bing"
check("Q2 mike_approval null cannot submit", raises(lambda: Q.submit_row(r0, login), Q.SubmitRefused))
check("Q2 the real queue rows (approval null, no login) cannot submit", all(raises(lambda r=r: Q.submit_row(r, login), Q.SubmitRefused) for r in rows))
for name, a in (("for another row id", {"approved_by": "mike", "at": "2026-10-19", "row_id": "fix-mapquest"}), ("by not mike", {"approved_by": "nate", "at": "2026-10-19", "row_id": r0["id"]}),
                ("without timestamp", {"approved_by": "mike", "row_id": r0["id"]}), ("string", "yes"), ("bool true", True)):
    check("Q2 approval %s cannot submit" % name, raises(lambda a=a: Q.submit_row(dict(r0, mike_approval=a), login), Q.SubmitRefused))
good = dict(r0, mike_approval={"approved_by": "mike", "at": "2026-10-19T16:00:00", "row_id": r0["id"]})
res = Q.submit_row(good, login)
check("Q2 valid approval + login returns a dry-run transition to submitted", res["dry_run"] is True and res["next_state"] == "submitted")
check("Q2 an already-submitted row cannot be submitted twice", raises(lambda: Q.submit_row(dict(good, state="submitted"), login), Q.SubmitRefused))
check("Q2 paid row refused", raises(lambda: Q.submit_row(dict(good, cost="paid $99"), login), Q.SubmitRefused))
check("Q3 no vaultwarden item name -> refused (login missing)", raises(lambda: Q.submit_row(dict(good, vaultwarden_item=None), login), Q.SubmitRefused))
check("Q3 getter returns nothing -> refused", raises(lambda: Q.submit_row(good, lambda i: None), Q.SubmitRefused))
def boom(i): raise RuntimeError("bw down SECRETPW")
try: Q.submit_row(good, boom); msg = ""
except Q.SubmitRefused as e: msg = str(e) + repr(e.__cause__) + repr(e.__context__ if not e.__suppress_context__ else None)
check("Q3 getter failure -> refused, no secret in the error", msg and "SECRETPW" not in msg)
src = open(os.path.join(HERE, "..", "job", "buildqueue.py"), encoding="utf-8").read()
check("Q4 buildqueue.py has no network/subprocess/browser import", not any(w in src for w in ("urllib", "requests", "subprocess", "socket", "import core", "owned_chrome", "import discover", "http.client")))
bad = {"fix_queue": [dict(rows[0], state="bogus")]}
check("Q5 invalid state rejected at load", raises(lambda: Q.parse_rows(bad), Q.QueueError))
check("Q5 duplicate ids rejected", raises(lambda: Q.parse_rows({"fix_queue": [rows[0], rows[0]]}), Q.QueueError))
print("\nALL PASS" if all(ok) else "\nFAILED", f"({sum(ok)}/{len(ok)})"); sys.exit(0 if all(ok) else 1)
