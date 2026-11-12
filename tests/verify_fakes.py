"""Fakes for the Verify Now bridge tests: a STRICT fake of the 4 agent RPCs (exact names and arg names; anything else raises), a
scripted Cylex page, a fake runtime with a virtual clock, and a fake card runner that dedupes on the idempotency key. No network."""
import contextlib, datetime, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "job"))
import portal as P
import verify_bridge as B

SCC, NM = P.ALLOWED["SCC"], P.ALLOWED["NM"]
RID = "aaaaaaaa-0000-4000-8000-000000000001"
VID = "bbbbbbbb-0000-4000-8000-000000000001"
NOW = datetime.datetime(2026, 11, 12, 18, 0, 0, tzinfo=datetime.timezone.utc)


def iso(dt): return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class StrictPortal:
    """Looks like portal.Portal.call. Holds request rows and verification rows. Raises AssertionError on any name or arg the contract does not list."""
    def __init__(self, requests=None, verifications=None, queued_code=None, finish_fails=False):
        self.requests = {r["id"]: dict(r) for r in (requests or [])}
        self.verifications = {v["id"]: dict(v) for v in (verifications or [])}
        self.queued_code = queued_code        # returned once by consume_verify_code, then null
        self.code_after_polls = 0             # consume returns null this many times first
        self.finish_fails = finish_fails      # finish_code_request raises (row stays stuck)
        self.calls = []
        self.finish_log = []
        self.sent_at = None                   # mark_code_sent stamps this (defaults to NOW)
        self.fail_mark = False; self.fail_patch = False; self.consume_calls = 0

    def _claimable(self):
        rows = sorted([r for r in self.requests.values() if r["status"] == "requested"], key=lambda r: r["requested_at"])
        return rows[0] if rows else None

    def call(self, method, path, body=None, prefer=None):
        self.calls.append((method, path.split("?")[0], body))
        if path.startswith("rpc/"):
            name = path[4:]
            if name == "claim_code_request":
                assert method == "POST" and body == {}, "claim_code_request takes no args"
                r = self._claimable()
                if not r: return None
                r["status"] = "starting"; r["claimed_at"] = iso(NOW); return dict(r)
            if name == "mark_code_sent":
                assert method == "POST" and set(body) == {"p_request_id", "p_sent_to_masked"}, "mark_code_sent arg names"
                assert B.MASK_RE.match(body["p_sent_to_masked"]), "mask shape"
                if self.fail_mark: raise RuntimeError("boom " + str(self.queued_code))
                if self.requests[body["p_request_id"]]["status"] != "starting": raise RuntimeError("mark_code_sent: not starting")   # portal PR #113: raises unless starting
                self.requests[body["p_request_id"]]["status"] = "code_sent"; self.requests[body["p_request_id"]]["code_sent_at"] = iso(self.sent_at or NOW); return None
            if name == "consume_verify_code":
                assert method == "POST" and set(body) == {"p_request_id"}, "consume_verify_code arg names"
                self.consume_calls += 1
                if self.consume_calls <= self.code_after_polls or not self.queued_code: return None
                c, self.queued_code = self.queued_code, None; return c
            if name == "finish_code_request":
                assert method == "POST" and set(body) == {"p_request_id", "p_status", "p_fail_code"}, "finish_code_request arg names"
                assert body["p_status"] in B.STATUSES
                assert (body["p_fail_code"] is None) if body["p_status"] == "verified" else body["p_fail_code"] in B.FAIL_CODES
                if self.finish_fails: raise RuntimeError("finish down")
                r = self.requests[body["p_request_id"]]
                self.finish_log.append((body["p_request_id"], body["p_status"], body["p_fail_code"]))
                if r["status"] in ("verified", "could_not_start", "failed"): return None   # portal PR #113: a no-op on a closed request, never raises
                if body["p_status"] == "verified":
                    v = self.verifications[r["citation_verification_id"]]
                    if v["state"] != "live": raise RuntimeError("verified refused: row not live")
                r["status"] = body["p_status"]; r["fail_code"] = body["p_fail_code"]; return None
            raise AssertionError("unknown rpc " + name)
        table, _, q = path.partition("?")
        params = dict(kv.split("=", 1) for kv in q.split("&") if "=" in kv)
        if table == B.REQUEST_TABLE and method == "GET":
            if "status" in params and params["status"].startswith("in."):
                want = params["status"][4:-1].split(",")
                key = "code_sent_at" if "code_sent_at" in params else "requested_at"
                return [dict(r) for r in self.requests.values() if r["status"] in want and r.get(key) and r[key] < params[key][3:]]
            if "id" not in params and params.get("status") == "eq.starting":   # the bridge's deferred-row list
                return [dict(r) for r in sorted(self.requests.values(), key=lambda r: r.get("claimed_at") or "") if r["status"] == "starting"]
            r = self.requests.get(params.get("id", "")[3:])
            if not r or ("status" in params and r["status"] != params["status"][3:]): return []
            return [dict(r)]
        if table == B.VERIFICATION_TABLE and method == "GET":
            v = self.verifications.get(params["id"][3:]); return [dict(v)] if v else []
        if table == B.VERIFICATION_TABLE and method == "PATCH":
            assert prefer == "return=representation" and body["state"] == "live"
            if self.fail_patch: return []
            v = self.verifications.get(params["id"][3:])
            if not v or v["client_id"] != params["client_id"][3:] or v["state"] != "requires_verification": return []
            v["state"] = "live"; v["verified_at"] = body["verified_at"]; return [dict(v)]
        raise AssertionError("unexpected portal call %s %s" % (method, path))

    def count(self, what): return sum(1 for c in self.calls if c[1] == what)


def request(rid=RID, client=NM, status="requested", age_s=5, channel="sms", vid=VID):
    return {"id": rid, "citation_verification_id": vid, "client_id": client, "channel": channel, "status": status,
            "requested_at": iso(NOW - datetime.timedelta(seconds=age_s)), "claimed_at": None, "code_sent_at": None}


def verification(vid=VID, client=NM, directory="cylex.us", state="requires_verification"):
    return {"id": vid, "client_id": client, "directory": directory, "state": state}


class FakeCards:
    """Stands in for `hermes kanban create`; dedupes on --idempotency-key like the real board."""
    def __init__(self): self.argvs, self.by_key = [], {}
    def __call__(self, argv, **kw):
        self.argvs.append(list(argv))
        key = argv[argv.index("--idempotency-key") + 1]
        self.by_key.setdefault(key, list(argv))
    @property
    def cards(self): return list(self.by_key)


class FakePage:
    """A scripted Cylex page. states: signin -> (access) -> account -> modal -> sent -> done."""
    def __init__(self, accepted="482913", phone="(502) 555-0101", access_gate=False, fill_raises=False, no_verify_btn=False, wrong_code_page=False, stay_on_password=False):
        self.state, self.accepted, self.phone = "signin", accepted, phone
        self.access_gate, self.fill_raises, self.no_verify_btn, self.wrong, self.stay_pw = access_gate, fill_raises, no_verify_btn, wrong_code_page, stay_on_password
        self.url = "https://www.cylex.us.com/signin/"; self.visits = []; self.actions = []; self.filled = []; self.sms_filled = None
        self.keyboard = self

    def press(self, key): self.actions.append(("press", key)); self.state = "account"
    def goto(self, url, **kw): self.visits.append(url); self.actions.append(("goto", url))
    def wait_for_timeout(self, ms): pass
    def fill(self, sel, text):
        self.actions.append(("fill", sel))
        if self.fill_raises and sel.startswith("input[autocomplete"): raise RuntimeError("fill failed for value " + text)
        if self.fill_raises and "code" in sel and self.state == "access": raise RuntimeError("fill failed for value " + text)
        self.filled.append((sel, text))
        if sel.startswith("input[autocomplete"): self.sms_filled = text
    def click(self, sel):
        self.actions.append(("click", sel))
        if sel == "button:has-text('Sign in')": self.state = "access" if self.access_gate else ("signin" if self.stay_pw else "account")
        elif sel == "button:has-text('Send verification code')": self.state = "sent"
        elif sel == "button:has-text('Verify')":
            self.state = "done" if (self.sms_filled == self.accepted and not self.wrong) else "badcode"
    def evaluate(self, js):
        self.actions.append(("evaluate", js[:40]))
        if "querySelector('#registerCompanyPhoneModalVerify').click()" in js: self.state = "modal"; return None
        if "innerText" in js: return ("Verify your phone number %s. I agree to receive a one-time code by SMS." % self.phone) if self.state == "modal" else ""
        return None
    def query_selector(self, sel):
        s = self.state
        if sel == "input[name*=code i]": return object() if s == "access" else None
        if sel == "input[type=password]": return object() if s == "signin" else None
        if sel == "#registerCompanyPhoneModalVerify": return object() if (s == "account" and not self.no_verify_btn) else None
        if sel == "button:has-text('Send verification code')": return object() if s == "modal" else None
        if sel.startswith("input[autocomplete"): return object() if s == "sent" else None
        return None
    def inner_text(self, sel):
        return {"done": "Verification completed", "badcode": "That code is invalid"}.get(self.state, "")


class Clock:
    def __init__(self): self.t = 1000.0; self.sleeps = []
    def now(self): return self.t
    def sleep(self, s): self.sleeps.append(s); self.t += s
    def wall(self): return NOW + datetime.timedelta(seconds=self.t - 1000.0)   # wall time on the same virtual clock (code_sent_at = NOW at t=1000)


class FakeRuntime:
    def __init__(self, page, clock=None, vault_ok=True, username=None, access=None, guard_ok=True, crash=False, agent_factory=None):
        self.crash, self.open_browsers = crash, 0
        self.username, self.prompts, self.launched, self.agent, self.agent_factory = username, [], [], None, agent_factory
        self.page, self.clock, self.vault_ok, self.access, self.guard_ok = page, clock or Clock(), vault_ok, access, guard_ok
        self.now, self.sleep, self.wall = self.clock.now, self.clock.sleep, self.clock.wall
        self.browsers = 0; self.reserves = []; self.vault_fills = 0; self.access_asked = 0
    def vault_lookup(self, tenant): return self.vault_ok
    def vault_fill(self, tenant, url, cdp): self.vault_fills += 1; return True
    def login_username(self, tenant):
        import verify_send as S
        return self.username if self.username is not None else S.EXPECTED_LOGIN[tenant[0]]
    def business_phone_masked(self, tenant): return "(502) ***-0101"
    def write_prompt(self, request_id, text):
        self.prompts.append(text); return "prompt-%s.txt" % request_id
    def launch_agent(self, path):
        self.launched.append(path); self.agent = self.agent_factory(self); return self.agent
    def mail_baseline(self, tenant): return set()
    def access_code(self, tenant, baseline): self.access_asked += 1; return self.access
    def guard(self):
        rt = self
        class G:
            def reserve(self, domain, key=None): rt.reserves.append((domain, key)); return {"ok": rt.guard_ok}
        return G()
    @contextlib.contextmanager
    def browser(self, tenant):
        self.browsers += 1; self.open_browsers += 1
        try:
            if self.crash: raise RuntimeError("chrome died")
            yield self.page, "http://127.0.0.1:1"
        finally:
            self.open_browsers -= 1


class FakeAgent:
    """Stands in for the hermes oneshot. `steps` are callables, one run per poll(); after the last one the process has exited (rc 0).
    hang=True never exits on its own. kill() records the kill and makes poll() report a dead process. No process is ever started."""
    def __init__(self, steps=(), hang=False):
        self.steps, self.hang, self.kills, self.polls = list(steps), hang, 0, 0
    def poll(self):
        self.polls += 1
        if self.kills: return -9
        if self.steps: self.steps.pop(0)()
        return None if (self.steps or self.hang) else 0
    def kill(self): self.kills += 1
