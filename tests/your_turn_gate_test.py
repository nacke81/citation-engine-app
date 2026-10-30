"""Your turn gate tests (t_e2db63f0). The 10/30 failure shapes from Mike's live run, plus the accepted shape. No network, no browser.
Run: python tests/your_turn_gate_test.py (CI)."""
import os, sys, json, shutil, tempfile, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json")
os.environ["CE_ACTIVITIES_WRITE"] = "0"; os.environ["CE_DIRECTORIES_WRITE"] = "0"
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "job"))
def _no_net(*a, **k): raise AssertionError("network call attempted")
urllib.request.urlopen = _no_net
import your_turn_gate as G, transitions as T, portal as P
from yt_obs import obs, _SHOT

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f"  [{d}]" if d else ""), flush=True)
DAY = "2026-10-30"
def has(probs, word): return any(word in p for p in probs)

# accepted: phone-call, observed phone-call, free, fresh, https, same domain
check("accept: phone-call seen, no price, this cycle", G.check_your_turn("yellowpages.com", "phone-call", obs("phone-call", DAY, url="https://www.yellowpages.com/claim/claim-verify", final_url="https://www.yellowpages.com/claim/claim-verify"), {"dead": False, "cost": "free"}, DAY) == [])
# 10/30 shape 1: ezlocal parked as sms, but the step is email only
p = G.check_your_turn("ezlocal.com", "sms", obs("email", DAY), {"dead": False, "cost": "unknown"}, DAY)
check("refuse: ezlocal email verify (agent job via listings@)", has(p, "email-verifiable"), p)
check("refuse: parked sms but observed email even if the row says sms", G.check_your_turn("ezlocal.com", "sms", obs("email", DAY), None, DAY) != [])
# shape 2: showmelocal $6.99
p = G.check_your_turn("showmelocal.com", "client-email", obs("client-email", DAY, price_seen="$6.99"), None, DAY)
check("refuse: showmelocal $6.99 claim (paid)", has(p, "paid"), p)
check("refuse: Directory DB cost=paid even when price_seen says none", has(G.check_your_turn("showmelocal.com", "client-email", obs("client-email", DAY), {"cost": "paid"}, DAY), "paid"))
# shape 3: com-yellowpages redirects to bestyell.com
p = G.check_your_turn("com-yellowpages.com", "phone-call", obs("phone-call", DAY, final_url="https://bestyell.com/"), None, DAY)
check("refuse: com-yellowpages.com redirects to bestyell.com", has(p, "redirect/dead"), p)
check("refuse: Directory DB dead flag", has(G.check_your_turn("com-yellowpages.com", "phone-call", obs("phone-call", DAY), {"dead": True, "dead_reason": "x"}, DAY), "dead"))
# shape 4: nothing observed (ibegin parked on a guess)
check("refuse: no observation at all", has(G.check_your_turn("ibegin.com", "phone-call", None, None, DAY), "no live observation"))
check("refuse: empty observation", G.check_your_turn("ibegin.com", "phone-call", {}, None, DAY) != [])
# missing pieces
check("refuse: no screenshot", has(G.check_your_turn("a.com", "phone-call", dict(obs("phone-call", DAY), screenshot=None), None, DAY), "screenshot"))
check("refuse: screenshot path does not exist", has(G.check_your_turn("a.com", "phone-call", dict(obs("phone-call", DAY), screenshot="C:/nope/none.png"), None, DAY), "screenshot"))
check("refuse: price not recorded", has(G.check_your_turn("a.com", "phone-call", dict(obs("phone-call", DAY), price_seen=None), None, DAY), "price_seen"))
check("refuse: stale observation (last cycle)", has(G.check_your_turn("a.com", "phone-call", obs("phone-call", "2026-10-10"), None, DAY), "this cycle"))
check("refuse: observation dated in the future", has(G.check_your_turn("a.com", "phone-call", obs("phone-call", "2026-11-30"), None, DAY), "this cycle"))
check("refuse: observed type differs from parked type", has(G.check_your_turn("a.com", "postcard", obs("phone-call", DAY), None, DAY), "!="))
check("refuse: http url / userinfo url", G.check_your_turn("a.com", "phone-call", obs("phone-call", DAY, url="http://a.com/v"), None, DAY) != [] and G.check_your_turn("a.com", "phone-call", obs("phone-call", DAY, url="https://u:p@a.com/v"), None, DAY) != [])
check("price words: free/none/0 pass, '$49.99/mo' and 'paid' refused", all(G.price_problem(x) is None for x in ("none", "free", 0, "0.00")) and all(G.price_problem(x) for x in ("$49.99/mo", "paid", 6.99, "abc")))

# wired into record_transition: refusal writes NOTHING
TMP = tempfile.mkdtemp(); QP = os.path.join(TMP, "q.json"); shutil.copy(os.path.join(HERE, "fixtures", "test_queue.json"), QP)
q = json.load(open(QP)); r0 = q["fix_queue"][0]; r0["state"] = "submitted"; json.dump(q, open(QP, "w"))
class Recorder:
    def __init__(s): s.calls = []; s.snaps = {}
    def latest_snapshot(s, cid): return None
    def upsert_snapshot(s, *a): s.calls.append(("snap",))
    def call(s, method, path, body=None, prefer=None):
        s.calls.append((method, path, body))
        if method == "GET": return [{"dead": True, "dead_reason": "redirects to bestyell.com", "cost": "unknown"}]
fp = Recorder(); before = open(QP, "rb").read()
refused = False
try: T.record_transition("SCC", r0["id"], "needs-human", None, None, queue_path=QP, today=DAY, portal=fp, verification=fp, directories=fp, verify_type="phone-call", observation=obs("phone-call", DAY))
except T.TransitionRefused as e: refused = "dead" in str(e)
check("record_transition: Directory DB dead flag refuses; queue file untouched; no write call", refused and open(QP, "rb").read() == before and not [c for c in fp.calls if c[0] != "GET"])
fp2 = Recorder(); refused = False
try: T.record_transition("SCC", r0["id"], "needs-human", None, None, queue_path=QP, today=DAY, portal=fp2, verification=fp2, directories=fp2, verify_type="phone-call")
except T.TransitionRefused as e: refused = "no live observation" in str(e)
check("record_transition: verify_type without observation refused, nothing written", refused and open(QP, "rb").read() == before and not [c for c in fp2.calls if c[0] != "GET"])
class OkDirs(Recorder):
    def call(s, method, path, body=None, prefer=None):
        s.calls.append((method, path, body)); return [{"dead": False, "dead_reason": None, "cost": "free"}] if method == "GET" else None
fp3 = OkDirs()
res = T.record_transition("SCC", r0["id"], "needs-human", None, None, queue_path=QP, today=DAY, portal=fp3, verification=fp3, directories=fp3, verify_type="phone-call", observation=obs("phone-call", DAY))
check("record_transition: a clean observation writes the Your turn row", res["verification_written"] is True and any(c[0] == "POST" and c[1].startswith("citation_verification") for c in fp3.calls))
check("the SCC non-production path never touches a portal seed/Directory action (only citation_verification, footprint_snapshot, ce_ tables)", all(("seed" not in str(c[1])) for c in fp3.calls if len(c) > 1 and isinstance(c[1], str)))
print("ALL PASS (%d/%d)" % (sum(ok), len(ok)) if all(ok) else "FAILED %d of %d" % (len(ok) - sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
