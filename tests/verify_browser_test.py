"""The verify agent prompt names the tenant's browser (t_45fe02d4). No Chrome, no hermes, no network: the process list, the port listing and OwnedChrome are fakes.
Run: python tests/verify_browser_test.py            (CI)
     python tests/verify_browser_test.py --mutations (CI) each mutation in a copy of job/ must make this suite FAIL."""
import contextlib, io, os, shutil, subprocess, sys, tempfile, types
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")

MUTATIONS = [
    ("swap the tenants' profiles", '"NM": ("nm-chrome-profile", 9334), "SCC": ("build-profile", 9333)', '"NM": ("build-profile", 9334), "SCC": ("nm-chrome-profile", 9333)'),
    ("swap the tenants' ports", '"NM": ("nm-chrome-profile", 9334), "SCC": ("build-profile", 9333)', '"NM": ("nm-chrome-profile", 9333), "SCC": ("build-profile", 9334)'),
    ("accept a port held by another profile", 'if not all(has_profile(procs.get(pid)) for pid in pids):', 'if False:'),
    ("prompt keeps the old 'reserved' wording", 'Use ONLY the browser at %(cdp)s (already open).', 'Use the one browser session this run reserved.'),
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
rt = S.Runtime()
NM_PROF, SCC_PROF = S.tenant_browser("NM")[0], S.tenant_browser("SCC")[0]

world({}, {}); del events[:]
with rt.agent_browser(NM_T) as url: inside = list(events); u = url
check("NM, nothing listening: OwnedChrome on the NM profile and 9334, open while the agent runs, closed after", inside == [("create", NM_PROF, 9334), ("open", NM_PROF, 9334)] and events[-1] == ("close", NM_PROF, 9334) and u == "http://127.0.0.1:9334", events)
check("NM never touched the SCC profile or 9333", all(SCC_PROF not in str(x) and 9333 not in x for x in events))
world({}, {}); del events[:]
with rt.agent_browser(SCC_T) as url: u = url
check("SCC, nothing listening: the SCC profile on 9333", events[0] == ("create", SCC_PROF, 9333) and u == "http://127.0.0.1:9333", events)

world({9334: [11]}, {11: chrome_cmd(NM_PROF, 9334)}); del events[:]
with rt.agent_browser(NM_T) as url: u = url
check("NM, 9334 already held by the NM profile: reused, no second Chrome, left running", events == [] and u == "http://127.0.0.1:9334", events)
world({9334: [11]}, {11: chrome_cmd(NM_PROF.replace("/", "\\"), 9334)}); del events[:]
with rt.agent_browser(NM_T) as url: u = url
check("same profile with backslashes still matches", events == [] and u == "http://127.0.0.1:9334", events)

for label, t, port, cmd in (("NM port held by the SCC profile", NM_T, 9334, chrome_cmd(SCC_PROF, 9334)),
                            ("SCC port held by the NM profile", SCC_T, 9333, chrome_cmd(NM_PROF, 9333)),
                            ("NM port held by a process with no profile", NM_T, 9334, "something.exe --serve"),
                            ("NM port held by a process we cannot read", NM_T, 9334, None)):
    world({port: [22]}, {22: cmd} if cmd else {}); del events[:]
    try:
        with rt.agent_browser(t): e = None
    except S.BrowserError as ex: e = str(ex)
    check("refused: %s, nothing started" % label, e is not None and "another profile" in e and events == [], (e, events))

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
order = []; p = portal(); rt = BrowserRuntime(order, refuse=True)
r = quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, F.NOW)
check("browser refused: failed/send_failed, no prompt, no agent, tenant lock free", r == "failed:send_failed" and rt.launched == [] and rt.prompts == [] and order == [] and not B.tenant_busy(F.NM) and p.requests[F.RID]["status"] == "failed", (r, order))

print("\n%d checks, %d failed" % (len(ok), ok.count(False)))
sys.exit(1 if False in ok else 0)
