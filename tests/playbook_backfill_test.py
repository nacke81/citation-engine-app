"""Playbook backfill + stale flag + trace-to-verify (t_2cb780c2). Offline: temp vault, fake DB, no network.
Run: python tests/playbook_backfill_test.py (CI). Exit 1 on any failure. The mutation checks at the end remove one guard and require the unsafe thing to HAPPEN."""
import hashlib, json, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import playbook as PB
import playbook_backfill as BF

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + ((" [%s]" % (d,)) if d != "" else ""), flush=True)

sha = lambda w: hashlib.sha256(w.encode()).hexdigest()
TENANT = "zorblaxco"   # a made-up tenant token; the real ones live only as hashes in tests/denylist.json
SC = BF.Scrubber(deny={sha(TENANT)}, id_words={"birchmedia"}, id_phones={"5025550101"})
vault = tempfile.mkdtemp()
def note(name, text):
    with open(os.path.join(vault, name), "w", encoding="utf-8") as f: f.write(text)

DIRS = [
    {"domain": "good.example", "name": "Good", "search_method": "own-search", "search_url_template": "https://www.good.example/s?q={name}&l={city}", "zero_marker_text": "0 results",
     "signup_url": "https://www.good.example/register", "claim_url": "https://www.good.example/claim", "claim_markers": "Unclaimed: a Claim button", "agent_access": "ok"},
    {"domain": "wall.example", "name": "Wall", "search_method": "not checked", "agent_access": "ok"},
    {"domain": "wallblocked.example", "name": "WB", "search_method": "not checked", "agent_access": "blocked"},
    {"domain": "dead.example", "name": "Dead", "search_method": "not checked", "signup_url": "https://dead.example/pro/signup", "agent_access": "unknown"},
    {"domain": "bare.example", "name": "Bare", "search_method": "not checked", "agent_access": "unknown"},
]
note("good.example.md", """# good.example (2026-11-10)
Outcome: live
Steps: open https://www.good.example/register?ref=abc123456 -> click the button `#signup-btn` -> fill `#email` with the login email listings@example.test.
Sign in at https://www.good.example/signin with vault item `SCC - good.example`, then click `#continue`.
Fill the phone field with (502) 555-0101 and press the Send code button.
Enter the code from the text message into the code field; the code input shows Verification completed.
Edit the profile page, change the hours field, and click Save.
Click the Claim button on the listing page https://www.good.example/company/39540176.
The weather was nice and the site was slow.
Click the Search button and type ZorblaxCo in the search field.
Click the Call button and dial (615) 555-0199.
Time: ~5 min
""")
note("wall.example.md", "# wall.example (2026-10-25)\nOutcome: needs-human (bot wall)\nSteps: navigate https://wall.example/ -> Cloudflare challenge.\n")
note("wallblocked.example.md", "# wallblocked.example (2026-10-25)\nOutcome: needs-human (bot wall)\nSteps: navigate https://wallblocked.example/ -> Cloudflare challenge.\n")
note("dead.example.md", "# dead.example (2026-10-26, Lis) - rejected no-fit\n/pro: \"You will only pay for leads from customers that choose you\". Pay-per-lead marketplace, /pro/signup is a 404.\n")
note("nm-good.example.md", "# NM good.example\n- Click the Dashboard tab and edit the billing page.\n")
note("_rules-x.md", "Click the button every time.\n")
note("ghost.example.md", "Click the button.\n")

rows, rep = BF.build(vault, DIRS, SC)
R = {(r["domain"], r["task"]): r for r in rows}
alltext = json.dumps(rows)

# ---- classification
check("1 claim words beat verify words", BF.classify("Click the Claim button then verify ownership") == "claim")
check("1 code/sms/sign in is verify", BF.classify("Enter the code from the text message") == "verify" and BF.classify("Sign in with the vault item") == "verify")
check("1 edit is fix, register is create, search is check", BF.classify("Edit the profile") == "fix" and BF.classify("Register a new account") == "create" and BF.classify("Search for the business") == "check")
check("1 narrative with no task word is unclassified", BF.classify("The weather was nice") is None)

# ---- rows
check("2 every row passes the playbook validator", all(PB.validate_steps(r["steps"]) for r in rows) and len(rows) > 0)
check("2 last_proven_at is null on every row", all(r["last_proven_at"] is None for r in rows))
check("2 field rows: check from own-search, create from signup_url, claim from claim_url", {("good.example", t) for t in ("check", "create", "claim")} <= set(R))
check("2 check steps use a placeholder, not a tenant value", any("{business_name}" in s["text"] for s in R[("good.example", "check")]["steps"]) and "0 results" in json.dumps(R[("good.example", "check")]["steps"]))
check("2 note sentences land under their task", ("good.example", "verify") in R and ("good.example", "fix") in R)
check("2 nm- note merges into the same Directory", "billing page" in json.dumps(R[("good.example", "fix")]), rep["unmapped_files"])
check("2 narrative is not a step", "weather" not in alltext)
check("2 _rules, ghost (no Directory) are not rows", "ghost.example" not in alltext and "ghost.example.md" in rep["unmapped_files"] and "_rules-x.md" in rep["skipped_files"])
check("2 source names where it came from", R[("good.example", "verify")]["source"].startswith("backfill") and "good.example.md" in R[("good.example", "verify")]["source"])

# ---- placeholders only
check("3 a tenant token drops the sentence (and is counted)", "zorblax" not in alltext.lower() and rep["dropped"].get("tenant token", 0) >= 1)
check("3 an email drops the sentence", "listings@" not in alltext and rep["dropped"].get("email address", 0) >= 1)
check("3 the identity phone becomes {phone}", "{phone}" in alltext and "555-0101" not in alltext)
check("3 a foreign phone drops the sentence", "555-0199" not in alltext)
check("3 a vault item name becomes {vault_item}", "{vault_item}" in alltext and "SCC - good" not in alltext)
check("3 a url loses its query and a listing id drops the url", "abc123456" not in alltext and "39540176" not in alltext and "https://www.good.example/register" in alltext)
check("3 the column on a 6+ digit run in text never reaches a row", not any(__import__("re").search(r"\d{6,}", s["text"]) for r in rows for s in r["steps"]))

# ---- stale
check("4 a rejected note is stale and still shows up", R[("dead.example", "create")]["stale"] is True and any("Old note" in s["text"] for s in R[("dead.example", "create")]["steps"]))
check("4 a stale Directory's field rows are stale too", "dead.example" in rep["stale_domains"] and all(r["stale"] for r in rows if r["domain"] == "dead.example"))
check("4 a wall note is stale when the Directory row says the agent has access", "wall.example" in rep["stale_domains"])
check("4 a wall note is NOT stale when the Directory is blocked", "wallblocked.example" not in rep["stale_domains"])
check("4 a good note is not stale", not R[("good.example", "verify")]["stale"] and rep["stale_rows"] == sum(1 for r in rows if r["stale"]))
check("4 counts per task add up", sum(rep["per_task"].values()) == len(rows) == rep["rows"] and set(rep["per_task"]) == set(PB.TASKS))

# ---- existing rows are never overwritten
rows2, rep2 = BF.build(vault, DIRS, SC, existing={("good.example", "verify")})
check("5 an existing (domain, task) is kept, not rebuilt", ("good.example", "verify") not in {(r["domain"], r["task"]) for r in rows2} and rep2["kept_existing"] == ["good.example/verify"])

# ---- CLI: dry run writes nothing, --write goes through set_playbook (with stale)
class Fake:
    def __init__(self, stored=None):
        self.calls, self.stored = [], stored or {}
    def call(self, method, path, body=None, prefer=None):
        self.calls.append((method, path, body))
        if method == "GET" and path.startswith("ce_directories?domain=eq."): return [{"domain": path.split("eq.")[1].split("&")[0]}]
        if method == "GET" and path.startswith("ce_directories?select"): return DIRS
        if method == "GET" and path.startswith("ce_directory_playbooks?select=domain,task"): return [{"domain": d, "task": t} for (d, t) in self.stored]
        if method == "GET": return []
        return None
BF.Scrubber.__init__.__defaults__   # (kept: constructor signature is part of the test surface)
lines = []
f1 = Fake()
orig_scr = BF.Scrubber
BF.Scrubber = lambda: SC
try:
    rc = BF.main(["--vault", vault, "--from-db"], db=f1, out=lines.append)
    check("6 dry run exits 0 and writes nothing", rc == 0 and not [c for c in f1.calls if c[0] == "POST"] and any("DRY RUN" in l for l in lines))
    f2 = Fake(stored={("good.example", "verify")})
    rc = BF.main(["--vault", vault, "--from-db", "--write"], db=f2, out=lambda m: None)
    posts = [c for c in f2.calls if c[0] == "POST"]
    wrote = [(p[2][0]["domain"], p[2][0]["task"]) for p in posts]
    nv = [r for r in rows if r["task"] != "verify"]; nverify = len(rows) - len(nv)
    check("6 --write upserts every planned NON-verify row through set_playbook; verify rows are skipped (a note cannot name the send step, t_8b8c2650)", rc == 0 and len(posts) == len([r for r in nv if (r["domain"], r["task"]) != ("good.example", "verify")]) and all(w[1] != "verify" for w in wrote), (len(posts), len(rows), wrote))
    check("6 a written row has no proven stamp, stale flagged where needed", all(p[2][0]["last_proven_at"] is None for p in posts) and any(p[2][0].get("stale") is True for p in posts))
finally:
    BF.Scrubber = orig_scr

# ---- playbook.py: stale param and trace
f3 = Fake()
r = PB.set_playbook(f3, "good.example", "check", [{"text": "Open the page"}], stale=True)
check("7 set_playbook sends stale only when asked", r["stale"] is True and "stale" not in PB.set_playbook(Fake(), "good.example", "check", [{"text": "Open the page"}]))
class Has(Fake):
    def call(self, method, path, body=None, prefer=None):
        if method == "GET" and path.startswith("ce_directory_playbooks?domain"): return [{"domain": "good.example", "task": "check", "version": 3, "stale": True}]
        return super().call(method, path, body, prefer)
r2 = PB.set_playbook(Has(), "good.example", "check", [{"text": "Open the page"}], last_proven_at="2026-11-13T10:00:00Z", stale=True)
check("7 a proven run clears stale (column present: false, version bumped)", r2["stale"] is False and r2["version"] == 4 and r2["last_proven_at"] == "2026-11-13T10:00:00Z")
r3 = PB.set_playbook(Has(), "good.example", "check", [{"text": "Open the page"}])
check("7 a plain re-set on a flagged row keeps the column explicit (false)", r3["stale"] is False)
trace = {"request_id": "r1", "domain": "good.example", "channel": "sms", "steps": [{"n": 1, "action": "goto", "url": "https://www.good.example/signin", "selector": None}, {"n": 2, "action": "fill", "url": "https://www.good.example/signin", "selector": "#email"}, {"n": 3, "action": "click", "url": "https://www.good.example/signin", "selector": "button[type=submit]"}]}
st = PB.steps_from_trace(trace)
check("8 a promote trace becomes verify steps (no typed value)", [s["text"] for s in st] == ["Open this page", "Fill in #email", "Click button[type=submit]"] and st[1]["selector"] == "#email" and "selector" not in st[0])
for bad, label in (({"steps": [{"action": "eval", "url": "https://a.example/"}]}, "unknown action"), ({"steps": []}, "empty"), ({"nope": 1}, "no steps"), ({"steps": [{"action": "click", "selector": "#a123456"}]}, "digit run selector")):
    try: PB.steps_from_trace(bad); got = None
    except PB.PlaybookError as e: got = str(e)
    check("8 trace refused: " + label, got is not None, got)
tf = os.path.join(vault, "t.json"); json.dump(trace, open(tf, "w"))
out = []; f4 = Fake()
rc0 = PB.main(["from-trace", "--file", tf], db=Fake(), out=out.append, err=lambda m: out.append(m))
check("8 from-trace without --send-step is refused (a verify playbook needs its one marked send)", rc0 == 1 and any("exactly one" in str(o) for o in out))
rc = PB.main(["from-trace", "--file", tf, "--send-step", "3"], db=f4, out=out.append)
w = [c for c in f4.calls if c[0] == "POST"][0][2][0]
check("8 from-trace without --proven leaves last_proven_at empty", rc == 0 and w["task"] == "verify" and w["last_proven_at"] is None and w["source"] == "run r1 (trace)")
f5 = Fake(); PB.main(["from-trace", "--file", tf, "--proven", "--send-step", "3"], db=f5, out=out.append)
w5 = [c for c in f5.calls if c[0] == "POST"][0][2][0]
check("8 from-trace --proven stamps last_proven_at", bool(w5["last_proven_at"]) and "stale" not in w5)

# ---- real vault (skipped when absent): every row validates and holds no denylisted token
if BF.VAULT_DEFAULT and os.path.isdir(BF.VAULT_DEFAULT):
    real_rows, real_rep = BF.build(BF.VAULT_DEFAULT, BF.load_dirs(), BF.Scrubber())
    deny = BF.load_denylist()
    leaked = [r["domain"] + "/" + r["task"] for r in real_rows if any(hashlib.sha256(w.encode()).hexdigest() in deny for w in __import__("re").findall(r"[a-z0-9]{3,}", json.dumps(r).lower()))]
    check("9 real vault: every row validates, none holds a denylisted token", all(PB.validate_steps(r["steps"]) for r in real_rows) and not leaked and len(real_rows) > 50, (len(real_rows), leaked[:3]))
else:
    print("SKIP 9 real vault not on this machine")

# ---- mutations: remove one guard, the unsafe thing must HAPPEN
bad_sc = BF.Scrubber(deny=set(), id_words=set(), id_phones=set(), use_deny=False)
mrows, _ = BF.build(vault, DIRS, bad_sc)
check("M1 without the tenant guard the tenant token DOES reach a row", "zorblax" in json.dumps(mrows).lower())
orig_stale = BF.note_stale
BF.note_stale = lambda md, d: None
mrows2, _ = BF.build(vault, DIRS, SC)
check("M2 without the stale check the rejected note is written as truth", not any(r["stale"] for r in mrows2 if r["domain"] == "dead.example"))
BF.note_stale = orig_stale

print("\n%d checks, %d failed" % (len(ok), ok.count(False)))
sys.exit(1 if False in ok else 0)
