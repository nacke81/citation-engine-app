"""The verify agent prompt names the tenant's browser (t_45fe02d4). No Chrome, no hermes, no network: the process list, the port listing and OwnedChrome are fakes.
Run: python tests/verify_browser_test.py            (CI)
     python tests/verify_browser_test.py --mutations (CI) each mutation in a copy of job/ must make this suite FAIL."""
import contextlib, io, os, shutil, subprocess, sys, tempfile, types
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")

MUTATIONS = [
    ("swap the tenants' profiles", '"NM": ("nm-chrome-profile", 9334), "SCC": ("build-profile", 9333)', '"NM": ("build-profile", 9334), "SCC": ("nm-chrome-profile", 9333)'),
    ("swap the tenants' ports", '"NM": ("nm-chrome-profile", 9334), "SCC": ("build-profile", 9333)', '"NM": ("nm-chrome-profile", 9333), "SCC": ("build-profile", 9334)'),
    ("accept a port held by another profile", 'if not all(same_profile(procs.get(pid), prof) for pid in pids):', 'if False:'),
    ("prompt keeps the old 'reserved' wording", 'Use ONLY the browser at %(cdp)s (already open).', 'Use the one browser session this run reserved.'),
    ("profile parse reverts to the round-1 regex (quote before the flag read as unquoted)", "    if m.group(1) or m.group(2):\n        end = rest.find('\"')", "    if m.group(2):\n        end = rest.find('\"')"),
    ("launch_agent drops BROWSER_CDP_URL", '        if cdp: env["BROWSER_CDP_URL"] = cdp', '        pass'),
    ("the agent run launches without the tenant's cdp url", "rt.launch_agent(rt.write_prompt(request_id, prompt), tenant_browser(tenant[0])[2])", "rt.launch_agent(rt.write_prompt(request_id, prompt))"),
    ("prompt drops --cdp for the fill helper", "always pass --cdp %(cdp)s.", "use the default browser."),
    ("SCC ignores a fresh build lease", 'if held and not str(held.get("card") or "").startswith(VERIFY_LEASE):', 'if False:'),
    ("SCC does not take its own lease", 'lease = KA.Lease("%s%d" % (VERIFY_LEASE, os.getpid())); lease.touch()', 'lease = KA.Lease("%s%d" % (VERIFY_LEASE, os.getpid()))'),
    ("SCC removes the lease even when a batch took it over", 'if cur and cur.get("card") == lease.card: KA.lease_release()', 'KA.lease_release()'),
    ("SCC lease is never refreshed", 'if cur and cur.get("card") == lease.card: lease.touch()', 'if cur: pass'),
]


def run_mutations():
    bad = 0
    for label, needle, repl in MUTATIONS:
        tmp = tempfile.mkdtemp()
        try:
            for d in ("job", "tests", "config"):
                shutil.copytree(os.path.join(ROOT, d), os.path.join(tmp, d), ignore=shutil.ignore_patterns("__pycache__", "playbooks"))
            f = os.path.join(tmp, "job", "verify_send.py")
            s = open(f, encoding="utf-8", newline="").read().replace("\r\n", "\n")
            if s.count(needle) < 1:
                print("MUTATION ERROR %s: needle not found" % label); bad += 1; continue
            open(f, "w", encoding="utf-8", newline="").write(s.replace(needle, repl))
            r = subprocess.run([sys.executable, os.path.join(tmp, "tests", "verify_browser_test.py")], capture_output=True, text=True, timeout=300)
            print(("KILLED   " if r.returncode != 0 else "SURVIVED ") + label); bad += 0 if r.returncode != 0 else 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print("mutations: %d, survived or broken: %d" % (len(MUTATIONS), bad))
    return 1 if bad else 0


if "--mutations" in sys.argv:
    sys.exit(run_mutations())

TMP = tempfile.mkdtemp()
os.environ["LOCALAPPDATA"] = os.path.join(TMP, "Mikes Desktop 2023", "AppData", "Local")   # same on every OS; a path with spaces, like the real one
os.environ["CE_BUILD_LEASE"] = os.path.join(TMP, "build-chrome.lease")
os.environ["CE_LOGS"] = os.path.join(TMP, "logs"); os.environ["CE_SITE_GUARD"] = os.path.join(TMP, "guard.json"); os.environ["CE_VERIFY_LOCKS"] = os.path.join(TMP, "locks")
os.environ["CE_VERIFY_DIRECTORIES"] = os.path.join(HERE, "verify_directories_fixture.json"); os.environ["CE_NO_CARDS"] = "1"
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json"); os.environ["CE_RUNS"] = tempfile.mkdtemp()
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, "job"))
import verify_fakes as F
import verify_bridge as B
import verify_send as S

ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + ((" [%s]" % (d,)) if d != "" else ""), flush=True)
def quiet(fn, *a, **kw):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*a, **kw)

ENTRY = {"domain": "agentdir.example", "signin_url": "https://agentdir.example/login"}
NM_T = ("NM", "Na" + "cke Media", "NM - agentdir.example", ENTRY["signin_url"])
SCC_T = ("SCC", "Senior Care Consulting", "SCC - agentdir.example", ENTRY["signin_url"])
PB = {"version": 3, "send_is_signup": False, "steps": [{"text": "Open the sign-in page"}, {"text": "Sign in"}, {"text": "Click the send button", "send": True}]}
PB_SIGNUP = dict(PB, send_is_signup=True)
def prompt(t, pb):
    return S.build_prompt(F.RID, F.request(channel="sms"), F.verification(directory=ENTRY["domain"]), ENTRY, t, "(502) ***-0101", "u@example.com", playbook=pb)

# ---- 1 the prompt ----------------------------------------------------------------------------------------------------------------
for label, pb in (("sign-in playbook", PB), ("signup playbook", PB_SIGNUP), ("no playbook", None)):
    nm, scc = prompt(NM_T, pb), prompt(SCC_T, pb)
    check("NM prompt (%s) says to use ONLY the browser at 9334, already open, no other browser; never 9333" % label,
          "Use ONLY the browser at http://127.0.0.1:9334 (already open). Do not open another browser." in nm and "9333" not in nm and "reserved" not in nm)
    check("SCC prompt (%s) names 9333 and never 9334" % label,
          "Use ONLY the browser at http://127.0.0.1:9333 (already open). Do not open another browser." in scc and "9334" not in scc and "reserved" not in scc)
check("the table: NM -> nm-chrome-profile/9334, SCC -> build-profile/9333, NM never the SCC profile",
      S.tenant_browser("NM")[0].replace("\\", "/").endswith("/citation-engine/nm-chrome-profile") and S.tenant_browser("NM")[1] == 9334
      and S.tenant_browser("SCC")[0].replace("\\", "/").endswith("/citation-engine/build-profile") and S.tenant_browser("SCC")[1] == 9333
      and S.tenant_browser("NM")[0] != S.tenant_browser("SCC")[0])
try: S.tenant_browser("OTHER"); e = None
except S.BrowserError as ex: e = str(ex)
check("an unknown tenant has no browser (fail closed)", e is not None, e)

# ---- 2 Runtime.agent_browser against fake processes ---------------------------------------------------------------------------------
import build_chrome as BC
events = []
class FakeOC:
    def __init__(self, profile=None, port=None): self.profile, self.port = profile, port; events.append(("create", profile, port))
    def __enter__(self): events.append(("open", self.profile, self.port)); return self
    def __exit__(self, *a): events.append(("close", self.profile, self.port)); return False
    @property
    def cdp_url(self): return "http://127.0.0.1:%d" % self.port
sys.modules["owned_chrome"] = types.SimpleNamespace(OwnedChrome=FakeOC)
def world(listening, procs):
    BC.listener_pids = lambda port, runner=None: list(listening.get(port, []))
    BC.list_procs = lambda runner=None: [{"pid": p, "ppid": 0, "cmd": c, "started": 0} for p, c in procs.items()]
def chrome_cmd(profile, port): return 'chrome.exe --remote-debugging-port=%d --user-data-dir="%s" about:blank' % (port, profile)
def main_cmd(profile, port): return '"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=%d "--user-data-dir=%s" --window-position=-32000,-32000 about:blank' % (port, profile)
rt = S.Runtime()
NM_PROF, SCC_PROF = S.tenant_browser("NM")[0], S.tenant_browser("SCC")[0]

world({}, {}); del events[:]
with rt.agent_browser(NM_T) as url: inside = list(events); u = url
check("NM, nothing listening: OwnedChrome on the NM profile and 9334, open while the agent runs, closed after", inside == [("create", NM_PROF, 9334), ("open", NM_PROF, 9334)] and events[-1] == ("close", NM_PROF, 9334) and u == "http://127.0.0.1:9334", events)
check("NM never touched the SCC profile or 9333", all(SCC_PROF not in str(x) and 9333 not in x for x in events))
import chrome_keepalive as KA
ups = []
KA.ensure_up = lambda port=KA.PORT, profile=KA.PROFILE, **kw: ups.append((profile, port)) or "restarted"
world({}, {}); del events[:]; del ups[:]
with rt.agent_browser(SCC_T) as url: u = url
check("SCC, nothing listening: build Chrome started detached on the SCC profile and 9333 (no OwnedChrome), and NOT closed by this run", ups == [(SCC_PROF, 9333)] and events == [] and u == "http://127.0.0.1:9333", (ups, events))

def reuse(label, t, port, cmd, want_url):
    """The port is held by a process whose command line is cmd: the run must reuse it, start nothing, leave it running. A refusal is a FAIL line."""
    world({port: [11]}, {11: cmd}); del events[:]
    try:
        with rt.agent_browser(t) as url: u, e = url, None
    except Exception as ex: u, e = None, "%s: %s" % (type(ex).__name__, ex)
    check(label, e is None and events == [] and u == want_url, (e, events))
reuse("NM, 9334 already held by the NM profile: reused, no second Chrome, left running", NM_T, 9334, chrome_cmd(NM_PROF, 9334), "http://127.0.0.1:9334")
reuse("same profile with backslashes still matches", NM_T, 9334, chrome_cmd(NM_PROF.replace("/", "\\"), 9334), "http://127.0.0.1:9334")
reuse("same profile with forward slashes still matches", NM_T, 9334, chrome_cmd(NM_PROF.replace("\\", "/"), 9334), "http://127.0.0.1:9334")
reuse("quote BEFORE the flag, as the live main process has it (profile path with spaces)", NM_T, 9334, main_cmd(NM_PROF, 9334), "http://127.0.0.1:9334")
reuse("different case and a trailing slash still match", NM_T, 9334, chrome_cmd(NM_PROF.upper() + "/", 9334), "http://127.0.0.1:9334")
# fixtures copied from the live command lines on this host (11/13): the 9334 main process, a 9334 renderer, the 9333 main process
LIVE_NM_MAIN = '"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9334 "--user-data-dir=C:/Users/Mikes Desktop 2023/AppData/Local/citation-engine/nm-chrome-profile" --window-position=-32000,-32000 --no-restore-session-state --disable-session-crashed-bubble about:blank'
LIVE_NM_RENDERER = '"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --type=renderer --user-data-dir="C:/Users/Mikes Desktop 2023/AppData/Local/citation-engine/nm-chrome-profile" --no-pre-read-main-dll --remote-debugging-port=9334 --lang=en-US'
LIVE_SCC_MAIN = '"C:/Program Files/Google/Chrome/Application/chrome.exe" --remote-debugging-port=9333 "--user-data-dir=C:\\Users\\Mikes Desktop 2023\\AppData\\Local\\citation-engine\\build-profile" --window-position=-32000,-32000 --window-size=1400,900 about:blank'
LIVE_NM_DIR = "C:/Users/Mikes Desktop 2023/AppData/Local/citation-engine/nm-chrome-profile"
LIVE_SCC_DIR = "C:\\Users\\Mikes Desktop 2023\\AppData\\Local\\citation-engine\\build-profile"
check("parse: live 9334 main process (quote before the flag) -> the whole path with spaces", S.cmd_user_data_dir(LIVE_NM_MAIN) == LIVE_NM_DIR, S.cmd_user_data_dir(LIVE_NM_MAIN))
check("parse: live 9334 renderer (quote after the =) -> the whole path", S.cmd_user_data_dir(LIVE_NM_RENDERER) == LIVE_NM_DIR, S.cmd_user_data_dir(LIVE_NM_RENDERER))
check("parse: live 9333 main process (backslashes) -> the whole path", S.cmd_user_data_dir(LIVE_SCC_MAIN) == LIVE_SCC_DIR, S.cmd_user_data_dir(LIVE_SCC_MAIN))
check("parse: bare unquoted value, and no flag at all", S.cmd_user_data_dir("chrome --user-data-dir=C:/p/x --a") == "C:/p/x" and S.cmd_user_data_dir("chrome --serve") is None)
check("compare: live NM line matches the NM dir in either slash style, never the SCC dir; live SCC line the reverse",
      S.same_profile(LIVE_NM_MAIN, LIVE_NM_DIR) and S.same_profile(LIVE_NM_MAIN, LIVE_NM_DIR.replace("/", "\\")) and not S.same_profile(LIVE_NM_MAIN, LIVE_SCC_DIR)
      and S.same_profile(LIVE_SCC_MAIN, LIVE_SCC_DIR) and S.same_profile(LIVE_SCC_MAIN, LIVE_SCC_DIR.replace("\\", "/")) and not S.same_profile(LIVE_SCC_MAIN, LIVE_NM_DIR))
check("compare: a prefix or a sibling directory is not the same profile", not S.same_profile(chrome_cmd(NM_PROF + "-old", 9334), NM_PROF) and not S.same_profile(chrome_cmd(os.path.dirname(NM_PROF), 9334), NM_PROF))

for label, t, port, cmd in (("NM port held by the SCC profile", NM_T, 9334, chrome_cmd(SCC_PROF, 9334)),
                            ("SCC port held by the NM profile", SCC_T, 9333, chrome_cmd(NM_PROF, 9333)),
                            ("NM port held by a process with no profile", NM_T, 9334, "something.exe --serve"),
                            ("NM port held by a process we cannot read", NM_T, 9334, None)):
    world({port: [22]}, {22: cmd} if cmd else {}); del events[:]
    try:
        with rt.agent_browser(t): e = None
    except S.BrowserError as ex: e = str(ex)
    check("refused: %s, nothing started" % label, e is not None and "another profile" in e and events == [], (e, events))

# ---- 2b SCC shares 9333 with build batches: lease check, own lease, refresh, release only if still ours -------------------------------------
import time
LP = KA.LEASE_PATH
check("test lease file is the temp one (never the real lease)", os.path.realpath(LP).startswith(os.path.realpath(TMP)), LP)
def lease_now(): return KA.lease_read(LP)
KA.lease_release(LP)
def scc_run(label, body=None):
    """-> (error text or None, lease seen inside, lease after). Chrome is not listening on 9333, ensure_up is the fake."""
    world({}, {}); del ups[:]; seen = {}
    try:
        with rt.agent_browser(SCC_T) as url:
            seen["inside"] = lease_now()
            if body: body()
        e = None
    except S.BrowserError as ex: e = str(ex)
    return e, seen.get("inside"), lease_now()

KA.lease_write("t_buildbatch", LP)
e, inside, after = scc_run("fresh build lease")
check("SCC refused while a build batch holds a fresh lease: BrowserError, Chrome not started, the batch's lease untouched", e is not None and "leased" in e and ups == [] and inside is None and after and after["card"] == "t_buildbatch", (e, ups, after))
KA.lease_write("t_oldbatch", LP, now=lambda: time.time() - KA.LEASE_TTL - 60)
e, inside, after = scc_run("stale build lease")
check("a stale build lease (older than the TTL) does not block SCC", e is None and ups == [(SCC_PROF, 9333)], (e, ups))
KA.lease_release(LP)
e, inside, after = scc_run("no lease")
check("SCC holds a verify lease for the whole run (the keepalive timer never fires under it) and releases it after", e is None and inside and inside["card"].startswith("verify:") and after is None, (e, inside, after))
KA.lease_write("verify:99999", LP)
e, inside, after = scc_run("own stale verify lease")
check("a leftover verify lease (the tenant lock proves no verify run is live) does not block SCC", e is None and inside and inside["card"].startswith("verify:"), (e, inside))
KA.lease_release(LP)

old_beat = S.LEASE_BEAT_S
seen_fresh = []
S.LEASE_BEAT_S = 0.05   # the thread reads it when it starts, so set it before entering
e, inside, after = scc_run("refresh 2", lambda: (KA.lease_write(lease_now()["card"], LP, now=lambda: time.time() - KA.LEASE_TTL - 60), time.sleep(0.4), seen_fresh.append(KA.lease_active(LP) is not None)))
S.LEASE_BEAT_S = old_beat
check("lease refreshed by the daemon thread: stale past the TTL, fresh again 0.4 s later", seen_fresh == [True], seen_fresh)

def takeover(): KA.lease_write("t_newbatch", LP)
e, inside, after = scc_run("takeover", takeover)
check("a batch that took the lease mid-run keeps it: SCC does not remove it", e is None and after and after["card"] == "t_newbatch", (e, after))
KA.lease_release(LP)

# NM never touches the build lease and is not blocked by it
KA.lease_write("t_buildbatch", LP); world({}, {}); del events[:]
try:
    with rt.agent_browser(NM_T) as url: nm_inside = lease_now(); e = None
except S.BrowserError as ex: e = str(ex)
check("NM (9334) is not blocked by a build lease, and leaves it alone", e is None and nm_inside["card"] == "t_buildbatch" and lease_now()["card"] == "t_buildbatch" and events[0] == ("create", NM_PROF, 9334), (e, events))
KA.lease_release(LP)
world({9333: [22]}, {22: chrome_cmd(NM_PROF, 9333)})
try:
    with rt.agent_browser(SCC_T): e = None
except S.BrowserError as ex: e = str(ex)
check("SCC refused for another profile on 9333 still releases its lease", e is not None and "another profile" in e and lease_now() is None, (e, lease_now()))

# ---- 2c the agent's env: hermes browser tools attach to the tenant's Chrome ---------------------------------------------------------
seen = {}
class FakeProc:
    pid = 4242
    def __init__(self, argv, **kw): seen["env"] = kw["env"]
    def poll(self): return None
    def kill(self): pass
os.environ["BROWSER_CDP_URL"] = "http://127.0.0.1:1111"   # an inherited value must never leak into the child
r2 = S.Runtime(popen=FakeProc, runner=lambda argv, **kw: None)
r2.launch_agent("C:/x/p.txt", "http://127.0.0.1:9334")
check("NM launch env: BROWSER_CDP_URL = the NM url (9334), never 9333, the inherited value gone", seen["env"].get("BROWSER_CDP_URL") == "http://127.0.0.1:9334" and "9333" not in str(seen["env"].get("BROWSER_CDP_URL")), seen["env"].get("BROWSER_CDP_URL"))
r2.launch_agent("C:/x/p.txt", "http://127.0.0.1:9333")
check("SCC launch env: BROWSER_CDP_URL = the SCC url (9333)", seen["env"].get("BROWSER_CDP_URL") == "http://127.0.0.1:9333", seen["env"].get("BROWSER_CDP_URL"))
r2.launch_agent("C:/x/p.txt")
check("no tenant url: no BROWSER_CDP_URL at all (not the inherited one)", "BROWSER_CDP_URL" not in seen["env"])
os.environ.pop("BROWSER_CDP_URL", None)
for label, pb in (("sign-in", PB), ("signup", PB_SIGNUP), ("no playbook", None)):
    nm, scc = prompt(NM_T, pb), prompt(SCC_T, pb)
    check("%s prompt tells the agent to pass --cdp <tenant url> to vaultwarden-cli-fill.js (NM 9334 / SCC 9333)" % label,
          "vaultwarden-cli-fill.js, always pass --cdp http://127.0.0.1:9334." in nm and "--cdp http://127.0.0.1:9333" not in nm
          and "vaultwarden-cli-fill.js, always pass --cdp http://127.0.0.1:9333." in scc and "--cdp http://127.0.0.1:9334" not in scc)

# ---- 3 the send run: the browser is up BEFORE the agent, closed after, and a refusal starts no agent -----------------------------------
AGENT_DIR = "agentdir.example"
def portal(client=F.NM):
    return F.StrictPortal(requests=[F.request(status="starting", channel="sms", client=client)], verifications=[F.verification(client=client, directory=AGENT_DIR)], queued_code="906417")
class BrowserRuntime(F.FakeRuntime):
    def __init__(self, order, refuse=False):
        F.FakeRuntime.__init__(self, F.FakePage(), agent_factory=lambda rt: (order.append("agent") or F.FakeAgent([])))
        self.order, self.refuse, self.tenants = order, refuse, []
    @contextlib.contextmanager
    def agent_browser(self, tenant):
        self.tenants.append(tenant[0])
        if self.refuse: raise S.BrowserError("port 9334 is held by a process with another profile")
        self.order.append("browser open")
        try: yield "http://127.0.0.1:%d" % S.tenant_browser(tenant[0])[1]
        finally: self.order.append("browser close")
order = []; p = portal(); rt = BrowserRuntime(order)
r, _ = (lambda o: (o, None))(quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, F.NOW))
check("browser open -> agent launched -> browser closed (in that order, once)", order == ["browser open", "agent", "browser close"] and rt.tenants == ["NM"], order)
check("the prompt the agent got names 9334", len(rt.prompts) == 1 and "http://127.0.0.1:9334 (already open)" in rt.prompts[0] and "9333" not in rt.prompts[0])
check("the run launched the agent with the NM cdp url (9334) for BROWSER_CDP_URL", getattr(rt, "launch_cdps", None) == ["http://127.0.0.1:9334"], getattr(rt, "launch_cdps", None))
order = []; p = portal(); rt = BrowserRuntime(order, refuse=True)
r = quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, F.NOW)
check("browser refused: failed/send_failed, no prompt, no agent, tenant lock free", r == "failed:send_failed" and rt.launched == [] and rt.prompts == [] and order == [] and not B.tenant_busy(F.NM) and p.requests[F.RID]["status"] == "failed", (r, order))

print("\n%d checks, %d failed" % (len(ok), ok.count(False)))
sys.exit(1 if False in ok else 0)
