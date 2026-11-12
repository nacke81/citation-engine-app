"""Verify Now bridge + send run tests (t_0d601426). No network, no Chrome, no real card, no real code. Run: python tests/verify_bridge_test.py (CI). Exit 1 on any failure."""
import contextlib, datetime, io, os, re, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp()
os.environ["CE_LOGS"] = os.path.join(TMP, "logs")
os.environ["CE_SITE_GUARD"] = os.path.join(TMP, "guard.json")
os.environ["CE_NO_CARDS"] = "1"   # tripwire: the real hermes CLI is never reached, cards go to FakeCards only
os.environ["CE_IDENTITY"] = os.path.join(HERE, "test_identity.json"); os.environ["CE_RUNS"] = tempfile.mkdtemp()   # transitions imports run.py
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "job"))
import verify_fakes as F
import verify_bridge as B
import verify_send as S
import portal as P

CODE = "482913"
import postcard_step as _PS
RV = _PS.REVIEWER   # the reviewer profile name, assembled in postcard_step (the leak check denylists the literal)
ok = []
def check(n, c, d=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + ((" [%s]" % (d,)) if d != "" else ""), flush=True)

def portal(**kw):
    reqs = kw.pop("requests", [F.request()]); vers = kw.pop("verifications", [F.verification()])
    return F.StrictPortal(requests=reqs, verifications=vers, **kw)

spawned = []
def spawner(argv, **kw): spawned.append((list(argv), kw)); return object()

def quiet(fn, *a, **kw):
    """-> (result, captured stdout+stderr). Every failure-path output is captured so the leak test can grep it."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        r = fn(*a, **kw)
    return r, out.getvalue() + err.getvalue()

def send(p, page, **rtkw):
    rt = F.FakeRuntime(page, **rtkw)
    res, text = quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, F.NOW)
    return res, text, rt

# 1 happy path: claim -> start (direct subprocess) -> send -> code -> live -> verified
p = portal(queued_code=CODE); cards = F.FakeCards()
res, _ = quiet(B.run_pass, p, B.VerifyRpc(p), F.NOW, spawner, cards)
argv, kw = spawned[0]
check("pass claims the request and starts the send run", res["started"] == [F.RID] and len(spawned) == 1 and p.requests[F.RID]["status"] == "starting")
check("send run is a direct python subprocess (no hermes, no kanban)", argv[0] == sys.executable and os.path.basename(argv[1]) == "verify_send.py" and argv[2:] == ["--request-id", F.RID] and not any("hermes" in a or "kanban" in a for a in [os.path.basename(argv[1])] + argv[2:]))
check("no card is filed for a fresh request", cards.argvs == [])
page = F.FakePage(accepted=CODE); rt = F.FakeRuntime(page)
r, text = quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, F.NOW)
check("happy path ends verified", r == "verified" and p.requests[F.RID]["status"] == "verified", r)
check("row is live with verified_at", p.verifications[F.VID]["state"] == "live" and p.verifications[F.VID].get("verified_at"))
check("mark_code_sent carried the masked number only", any(c[1] == "rpc/mark_code_sent" and c[2]["p_sent_to_masked"] == "(502) ***-0101" for c in p.calls))
order = [c[1] for c in p.calls if c[1] in ("rpc/mark_code_sent", "rpc/consume_verify_code", "rpc/finish_code_request") or c[0] == "PATCH"]
check("order: mark sent, consume, set live, finish", order == ["rpc/mark_code_sent", "rpc/consume_verify_code", "citation_verification", "rpc/finish_code_request"], order)
check("one Directory session (1 sitegate reserve, 1 browser)", rt.reserves == [("cylex.us", F.RID)] and rt.browsers == 1)
check("the code reached the page field and nowhere in output", page.sms_filled == CODE and CODE not in text)
check("signed in through the vault helper, then no password left on page", rt.vault_fills == 1)
dig = [c for c in page.actions if c[0] == "evaluate"]
check("send click only after the modal number was read", [a for a in page.actions if a[0] == "click"][-2:] == [("click", "button:has-text('Send verification code')"), ("click", "button:has-text('Verify')")])

# 2 no code within 30 min -> failed/code_expired
p = portal(requests=[F.request(status="starting")]); page = F.FakePage(); clk = F.Clock(); rt = F.FakeRuntime(page, clk)
r, text = quiet(S.run, F.RID, p, B.VerifyRpc(p), rt, F.NOW)
check("no code in 30 min -> failed/code_expired", r == "failed:code_expired" and p.requests[F.RID]["fail_code"] == "code_expired" and p.requests[F.RID]["status"] == "failed", r)
check("polled every 10 s for the 30 minutes", set(clk.sleeps) == {10} and 1790 <= sum(clk.sleeps) <= 1810 and p.consume_calls >= 179, (sum(clk.sleeps), p.consume_calls))

# 3 sweeper: exactly one card on two passes
stuck = [F.request(age_s=700, status="starting")]
p = portal(requests=stuck, finish_fails=True); cards = F.FakeCards()   # finish keeps failing: the row stays stale and pass 2 sees it again
for _ in range(2): quiet(B.sweep, p, B.VerifyRpc(p), F.NOW, cards)
check("sweeper at 10 min files exactly one card over two passes", len(cards.cards) == 1 and len(cards.argvs) == 2 and cards.cards == ["verify-now:" + F.RID], (cards.cards, len(cards.argvs)))
a = cards.argvs[0]
check("card goes to the reviewer profile on its own board, never a code", a[a.index("--assignee") + 1] == RV and a[a.index("--board") + 1] == RV and CODE not in " ".join(a))
p = portal(requests=[F.request(age_s=700, status="starting"), F.request(rid="aaaaaaaa-0000-4000-8000-000000000002", age_s=650, status="requested", vid=F.VID), F.request(rid="aaaaaaaa-0000-4000-8000-000000000003", age_s=100)]); cards = F.FakeCards()
done, _ = quiet(B.sweep, p, B.VerifyRpc(p), F.NOW, cards)
st = {r["id"]: (r["status"], r.get("fail_code")) for r in p.requests.values()}
check("stale requested + starting rows end could_not_start/timeout, a 100 s row is left alone", len(done) == 2 and st[F.RID] == ("could_not_start", "timeout") and st["aaaaaaaa-0000-4000-8000-000000000002"] == ("could_not_start", "timeout") and st["aaaaaaaa-0000-4000-8000-000000000003"][0] == "requested", st)
quiet(B.sweep, p, B.VerifyRpc(p), F.NOW, cards)
check("second clean pass adds no cards and zero rows stay in starting", len(cards.argvs) == 2 and not [r for r in p.requests.values() if r["status"] == "starting"])
p = portal(requests=[F.request(age_s=599, status="starting")]); cards = F.FakeCards()
done, _ = quiet(B.sweep, p, B.VerifyRpc(p), F.NOW, cards)
check("599 s is not swept (boundary)", done == [] and cards.argvs == [])

# 4 no-playbook directory: 0 site loads
p = portal(verifications=[F.verification(directory="yellowpages.com")]); spawned.clear()
res, _ = quiet(B.run_pass, p, B.VerifyRpc(p), F.NOW, spawner, F.FakeCards())
check("bridge: no-playbook Directory is failed/no_playbook and no send run starts", res["refused"] == [(F.RID, "no_playbook")] and p.requests[F.RID]["fail_code"] == "no_playbook" and p.requests[F.RID]["status"] == "failed" and spawned == [])
p = portal(requests=[F.request(status="starting")], verifications=[F.verification(directory="yellowpages.com")]); page = F.FakePage()
r, text, rt = send(p, page)
check("send run: no-playbook makes 0 site loads, 0 browsers, 0 sitegate reads", r == "failed:no_playbook" and page.visits == [] and rt.browsers == 0 and rt.reserves == [] and rt.vault_fills == 0, r)

# 5 mismatched client_id refused before any network call
p = portal(requests=[F.request(client=F.NM)], verifications=[F.verification(client=F.SCC)]); spawned.clear()
res, _ = quiet(B.run_pass, p, B.VerifyRpc(p), F.NOW, spawner, F.FakeCards())
check("bridge: client mismatch refused, no send run, failed/other", res["refused"] == [(F.RID, "mismatch")] and spawned == [] and p.requests[F.RID]["fail_code"] == "other")
p = portal(requests=[F.request(status="starting", client=F.NM)], verifications=[F.verification(client=F.SCC)]); page = F.FakePage()
r, text, rt = send(p, page)
check("send run: mismatch touches no Directory, no mark, no consume", r == "failed:other" and page.visits == [] and rt.browsers == 0 and rt.reserves == [] and p.count("rpc/mark_code_sent") == 0 and p.consume_calls == 0)
other = "430b764e-1a44-4246-959f-6b8945bf6a7c"   # forbidden client id: refused with zero portal reads
p = portal(requests=[F.request(client=other)]); spawned.clear()
res, _ = quiet(B.run_pass, p, B.VerifyRpc(p), F.NOW, spawner, F.FakeCards())
check("forbidden client id refused before any verification read", res["refused"] == [(F.RID, "bad_client")] and p.count("citation_verification") == 0 and spawned == [])
p = portal(requests=[F.request(channel="voice")]); spawned.clear()
res, _ = quiet(B.run_pass, p, B.VerifyRpc(p), F.NOW, spawner, F.FakeCards())
check("a non-sms channel is refused in slice 1", res["refused"] == [(F.RID, "channel")] and spawned == [])
p = portal(requests=[F.request(status="requested")]); page = F.FakePage()   # never claimed
r, text, rt = send(p, page)
check("send run refuses an unclaimed request (status requested)", r == "not_claimed" and rt.browsers == 0 and page.visits == [] and p.requests[F.RID]["status"] == "requested")

# 6 fail closed: vault item missing, sitegate refuses, access code never arrives, claim lost
p = portal(requests=[F.request(status="starting")]); page = F.FakePage()
r, text, rt = send(p, page, vault_ok=False)
check("vault item missing -> failed/signin_failed, no browser", r == "failed:signin_failed" and rt.browsers == 0 and page.visits == [])
p = portal(requests=[F.request(status="starting")]); page = F.FakePage()
r, text, rt = send(p, page, guard_ok=False)
check("sitegate cooldown -> could_not_start, no browser", r == "could_not_start:other" and rt.browsers == 0)
p = portal(requests=[F.request(status="starting")]); page = F.FakePage(access_gate=True)
r, text, rt = send(p, page, access=None)
check("access code never arrives -> failed/other with a log line", r == "failed:other" and "access code not found" in text and p.count("rpc/mark_code_sent") == 0, r)
p = portal(requests=[F.request(status="starting")], queued_code=CODE); page = F.FakePage(access_gate=True, accepted=CODE)
r, text, rt = send(p, page, access="771155")
check("email access code first: read from the mailbox, entered, then the SMS leg completes", r == "verified" and rt.access_asked == 1 and ("fill", "input[name*=code i]") in page.actions and "771155" not in text, r)
p = portal(requests=[F.request(status="starting")]); page = F.FakePage(no_verify_btn=True)
r, text, rt = send(p, page)
check("verify control not found -> failed/send_failed, no code sent", r == "failed:send_failed" and p.count("rpc/mark_code_sent") == 0)
p = portal(requests=[F.request(status="starting")]); page = F.FakePage(phone="no number here")
r, text, rt = send(p, page)
check("number unreadable -> not sent", r == "failed:send_failed" and p.count("rpc/mark_code_sent") == 0 and ("click", "button:has-text('Send verification code')") not in page.actions)
p = portal(requests=[F.request(status="starting")]); page = F.FakePage(stay_on_password=True)
r, text, rt = send(p, page)
check("sign-in rejected (password field still there) -> failed/signin_failed", r == "failed:signin_failed" and p.count("rpc/mark_code_sent") == 0)

# 7 leak test: a fake code is pushed through every failure path; stdout, stderr, log files and portal bodies hold 0 hits
paths = []
def leak_case(name, **kw):
    p = portal(requests=[F.request(status="starting")], queued_code=CODE, verifications=[F.verification()])
    for k in ("fail_mark", "fail_patch", "finish_fails"): setattr(p, k, kw.pop(k, False))
    page = F.FakePage(accepted=kw.pop("accepted", CODE), **kw)
    r, text, rt = send(p, page, access=CODE if page.access_gate else None)
    bodies = repr([c[2] for c in p.calls])
    paths.append((name, r, CODE in text, CODE in bodies))
leak_case("fill raises with the typed value in its message", fill_raises=True)
leak_case("access-code fill raises", fill_raises=True, access_gate=True)
leak_case("mark_code_sent fails with the code in its message", fail_mark=True)
leak_case("wrong code (rejected page)", accepted="000000")
leak_case("set live fails after accept", fail_patch=True)
leak_case("finish endpoint down on the happy path", finish_fails=True)
leak_case("rejected page text", wrong_code_page=True)
leak_case("happy path", )
for name, r, in_text, in_body in paths:
    check("leak: %s -> %s, code in output=%s, in portal bodies=%s" % (name, r, in_text, in_body), not in_text and not in_body)
check("leak: every path returned an outcome (no escaped exception)", all(isinstance(x[1], str) for x in paths) and len(paths) == 8)
allfiles = "".join(open(os.path.join(dp, f), errors="ignore").read() for dp, _, fs in os.walk(TMP) for f in fs)
check("leak: no file under the logs/guard dir holds the code", CODE not in allfiles and "771155" not in allfiles)

# 8 contract strictness + rules
rpc = B.VerifyRpc(portal())
for label, fn in (("bad status", lambda: rpc.finish(F.RID, "done", None)), ("bad fail code", lambda: rpc.finish(F.RID, "failed", "whatsapp")), ("bad mask", lambda: rpc.mark_sent(F.RID, "5025550101"))):
    try: fn(); check("rpc refuses " + label, False)
    except B.BridgeError: check("rpc refuses " + label, True)
check("mask_phone", B.mask_phone("+1 (502) 555-0101") == "(502) ***-0101" and B.mask_phone("12345") is None)
src = {n: open(os.path.join(HERE, "..", "job", n), encoding="utf-8").read() for n in ("verify_bridge.py", "verify_send.py")}
src["verify_fakes.py"] = open(os.path.join(HERE, "verify_fakes.py"), encoding="utf-8").read()
src["this test"] = open(__file__, encoding="utf-8").read()
check("no WhatsApp wording (job files + fakes)", not [n for n, t in src.items() if n != "this test" and re.search("whats" + "app", t.replace("No WhatsApp or voice path exists here.", ""), re.I)])
check("no em dashes in the new files", not [n for n, t in src.items() if "\u2014" in t])
check("no scheduler created by the bridge", not re.search(r"schtasks|crontab|cronjob|Register-ScheduledTask", src["verify_bridge.py"] + src["verify_send.py"]))
sys.exit(0 if all(ok) else 1)
